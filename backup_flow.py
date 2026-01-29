"""Backup flow orchestration.

Provides a simple orchestration layer that ties together path discovery,
pre/post hooks, borg archive creation and state updates for a single
service or all services in the configuration.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from borg import run_borg_create
from commands import run_hooks
from docker_introspect import discover_paths
from state_store import update_last_success_archive

logger = logging.getLogger(__name__)


def _get_service_name_from_config(service_config: dict) -> str:
    """Return the logical service name from service_config.

    The configuration may provide an explicit "name" field. If not present
    the function will fall back to a generic placeholder. Callers that know
    the service name (for example when iterating a mapping) should set the
    "name" key on the service_config before calling backup_service to ensure
    consistent naming.
    """
    name = service_config.get("name")
    if isinstance(name, str) and name:
        return name
    # Try common alternative keys
    alt = service_config.get("service") or service_config.get("service_name")
    if isinstance(alt, str) and alt:
        return alt
    return "<unknown>"


def backup_service(config: Dict, service_config: Dict) -> bool:
    """Orchestrate the backup process for a single service.

    Steps executed (in order):
      1. Path discovery via docker_introspect.discover_paths
      2. Run pre-backup hooks (if any) using commands.run_hooks
      3. Execute borg.create to create the archive
      4. Run post-backup hooks (if any) using commands.run_hooks
      5. If borg succeeded, persist archive name via state_store.update_last_success_archive

    Args:
        config: Global configuration dictionary.
        service_config: Per-service configuration dictionary. It is expected
            to contain identifying information for the service. If a
            "name" key is present it will be used as the logical service
            name. If omitted, a best-effort fallback is used.

    Returns:
        True when the backup flow completed successfully and the archive
        state was persisted. False on any failure. Note that post-hooks are
        always attempted when borg create ran (even if borg failed) but
        their failure does not change the overall result.
    """
    service_name = _get_service_name_from_config(service_config)
    logger.info("Starting backup for service: %s", service_name)

    # 1) Path discovery
    try:
        paths: List[str] = discover_paths(service_config)
    except Exception as exc:
        logger.exception("Path discovery failed for %s: %s", service_name, exc)
        logger.info("Finished backup for service: %s (result=FAIL)", service_name)
        return False

    logger.info("Discovered %d path(s) for service %s", len(paths), service_name)

    # 2) Run pre-backup hooks (fail-fast). Call run_hooks even when no explicit
    # commands are configured so test and integration code can rely on the
    # hook execution path being exercised; an empty list is a no-op.
    backup_commands = service_config.get("backup_commands") or {}
    pre_cmds = backup_commands.get("pre") if isinstance(backup_commands, dict) else None
    logger.info("Running pre-backup hooks for service: %s", service_name)
    try:
        ok_pre = run_hooks(pre_cmds or [], "pre")
    except Exception:
        logger.exception(
            "Unexpected error while running pre-hook commands for %s", service_name
        )
        ok_pre = False
    if not ok_pre:
        logger.error("Pre-backup hooks failed for %s; aborting backup", service_name)
        logger.info("Finished backup for service: %s (result=FAIL)", service_name)
        return False

    # 3) Borg create
    borg_succeeded = False
    archive_name = None
    try:
        borg_succeeded, archive_name = run_borg_create(config, service_name, paths)
    except Exception:
        logger.exception(
            "Unexpected error while running borg create for %s", service_name
        )
        borg_succeeded = False
        archive_name = None

    if borg_succeeded:
        logger.info("Borg create succeeded for %s -> %s", service_name, archive_name)
    else:
        logger.error("Borg create failed for %s", service_name)

    # 4) Post-backup hooks: attempt regardless of borg result (unless pre-hooks
    # had aborted earlier). Failures here are logged but don't change result.
    post_cmds = (
        backup_commands.get("post") if isinstance(backup_commands, dict) else None
    )
    # Always attempt post hooks after borg create ran (even on failure).
    logger.info("Running post-backup hooks for service: %s", service_name)
    try:
        ok_post = run_hooks(post_cmds or [], "post")
    except Exception:
        logger.exception(
            "Unexpected error while running post-hook commands for %s", service_name
        )
        ok_post = False
    if not ok_post:
        logger.error("One or more post-backup hooks failed for %s", service_name)

    # 5) Update state when borg succeeded
    if borg_succeeded and archive_name:
        try:
            updated = update_last_success_archive(service_name, archive_name)
            if not updated:
                logger.error(
                    "Failed to persist last_success_archive for %s", service_name
                )
                # Treat inability to persist as a failure of the overall flow
                logger.info(
                    "Finished backup for service: %s (result=FAIL)", service_name
                )
                return False
        except Exception:
            logger.exception("Exception while updating state for %s", service_name)
            logger.info("Finished backup for service: %s (result=FAIL)", service_name)
            return False

    result = borg_succeeded and bool(archive_name)
    logger.info(
        "Finished backup for service: %s (result=%s)",
        service_name,
        "OK" if result else "FAIL",
    )
    return result


def backup_all_services(config: Dict) -> Dict[str, bool]:
    """Run backup flow for all services in the provided configuration.

    Iterates through config["services"] and invokes :func:`backup_service`
    for every configured service. The function continues to attempt backups
    for remaining services even if some fail.

    Args:
        config: Global configuration dictionary expected to contain a
            "services" mapping or sequence.

    Returns:
        A mapping of service_name -> boolean indicating success (True) or
        failure (False) for each attempted service.
    """
    results: Dict[str, bool] = {}
    services = config.get("services") or {}

    # Accept either a mapping of name->config or a list of config entries
    if isinstance(services, dict):
        iterator = services.items()
    elif isinstance(services, list):
        # list of service configs, each is expected to contain a "name"
        iterator = ((_get_service_name_from_config(svc), svc) for svc in services)
    else:
        logger.warning("Unexpected services configuration type: %s", type(services))
        iterator = []

    for svc_name, svc_cfg in iterator:
        # Ensure the service config knows its name so downstream callers can
        # use it when necessary.
        if isinstance(svc_cfg, dict):
            svc_cfg.setdefault("name", svc_name)
        else:
            logger.warning(
                "Skipping service %s because its config is not a mapping", svc_name
            )
            results[str(svc_name)] = False
            continue

        logger.info("Beginning backup for configured service: %s", svc_name)
        try:
            ok = backup_service(config, svc_cfg)
        except Exception:
            logger.exception(
                "Unhandled exception while backing up service: %s", svc_name
            )
            ok = False
        results[svc_name] = ok

    # Summary logging
    succeeded = [n for n, ok in results.items() if ok]
    failed = [n for n, ok in results.items() if not ok]
    logger.info(
        "Backup summary: total=%d succeeded=%d failed=%d",
        len(results),
        len(succeeded),
        len(failed),
    )
    if succeeded:
        logger.info("Succeeded services: %s", ", ".join(succeeded))
    if failed:
        logger.info("Failed services: %s", ", ".join(failed))

    return results
