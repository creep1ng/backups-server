"""Restore flow orchestration.

Provides the steps needed to execute restoration of a single service using
`borg extract` and the configured hooks. Mirrors the structure of
`backup_flow` but targets restore-specific operations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from borg import run_borg_extract, run_borg_list_archives
from commands import run_hooks
from remote_listing import process_remote_archives
from state_store import get_last_success_archive

logger = logging.getLogger(__name__)


class RestoreError(Exception):
    """Indicates user-visible restore failures."""


def _get_service_config(config: Dict[str, Any], service_name: str) -> Dict[str, Any]:
    """Locate the configuration block for the requested service."""

    services = config.get("services") or {}

    if isinstance(services, dict):
        svc = services.get(service_name)
        if isinstance(svc, dict):
            svc.setdefault("name", service_name)
            return svc
    elif isinstance(services, list):
        for svc in services:
            if isinstance(svc, dict) and svc.get("name") == service_name:
                svc.setdefault("name", service_name)
                return svc

    raise RestoreError(f"Service '{service_name}' is not configured")


def _prepare_staging_dir(path: Path, force: bool) -> None:
    """Ensure the staging directory exists and is safe to write into."""

    if path.exists():
        if not path.is_dir():
            raise RestoreError(f"Staging path {path} exists and is not a directory")
        if not force and any(path.iterdir()):
            raise RestoreError(
                f"Staging directory {path} is not empty; use --force to overwrite"
            )
    else:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.exception("Failed to create staging directory %s", path)
            raise RestoreError(
                f"Unable to prepare staging directory {path}: {exc}"
            ) from exc


def resolve_latest_archive_name(config: Dict[str, Any], service_name: str) -> str:
    """Resolve the archive name to restore when --latest is requested."""

    _get_service_config(config, service_name)

    raw_candidate = get_last_success_archive(service_name)
    try:
        success, raw_archives, error = run_borg_list_archives(config, [service_name])
    except KeyError as exc:
        raise RestoreError(
            "Storage box configuration is incomplete; cannot resolve repository"
        ) from exc

    if not success:
        raise RestoreError(f"Failed to list archives: {error or 'unknown error'}")

    if not raw_archives:
        raise RestoreError("Borg repository contains no archives")

    processed = process_remote_archives(raw_archives, config, services=[service_name])

    if not processed:
        raise RestoreError(f"No archives found for service '{service_name}'")

    if raw_candidate:
        for record in processed:
            if record.archive == raw_candidate:
                logger.info(
                    "Using last_success_archive '%s' for service %s",
                    raw_candidate,
                    service_name,
                )
                return raw_candidate
        logger.warning(
            "last_success_archive '%s' not present in repository; falling back to remote listing",
            raw_candidate,
        )

    latest = processed[0]
    # process_remote_archives returns records sorted by service -> time desc -> archive asc,
    # so first entry is deterministically the newest archive for the service. Ties at the
    # same timestamp are resolved by lexicographically smaller archive names.
    logger.info(
        "Resolved latest archive '%s' for service %s",
        latest.archive,
        service_name,
    )
    return latest.archive


def restore_service(
    config: Dict[str, Any],
    service_name: str,
    archive_name: str,
    staging_dir: str,
    force: bool = False,
) -> bool:
    """Restore the requested archive into the staging directory."""

    service_config = _get_service_config(config, service_name)
    logger.info("Starting restore for service: %s", service_name)

    restore_commands = service_config.get("restore_commands") or {}
    pre_cmds = (
        restore_commands.get("pre") if isinstance(restore_commands, dict) else None
    )
    logger.info("Running pre-restore hooks for service: %s", service_name)
    try:
        ok_pre = run_hooks(pre_cmds or [], "pre")
    except Exception:
        logger.exception(
            "Unexpected error while running restore pre-hooks for %s", service_name
        )
        ok_pre = False
    if not ok_pre:
        logger.error("Pre-restore hooks failed for %s; aborting restore", service_name)
        logger.info("Finished restore for service: %s (result=FAIL)", service_name)
        return False

    staging_path = Path(staging_dir)
    try:
        _prepare_staging_dir(staging_path, force)
    except RestoreError as exc:
        logger.error("Staging directory validation failed: %s", exc)
        logger.info("Finished restore for service: %s (result=FAIL)", service_name)
        return False

    extract_success = False
    try:
        extract_success = run_borg_extract(config, archive_name, str(staging_path))
    except Exception:
        logger.exception(
            "Unexpected error while running borg extract for %s", service_name
        )
        extract_success = False

    post_cmds = (
        restore_commands.get("post") if isinstance(restore_commands, dict) else None
    )
    logger.info("Running post-restore hooks for service: %s", service_name)
    try:
        ok_post = run_hooks(post_cmds or [], "post")
    except Exception:
        logger.exception(
            "Unexpected error while running restore post-hooks for %s", service_name
        )
        ok_post = False
    if not ok_post:
        logger.error("One or more post-restore hooks failed for %s", service_name)

    result = extract_success and ok_post
    logger.info(
        "Finished restore for service: %s (result=%s)",
        service_name,
        "OK" if result else "FAIL",
    )
    return result
