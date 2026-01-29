"""Borg operations module.

Provides helpers to build and run borg create commands for incremental
snapshots without intermediate tar files.
"""

from __future__ import annotations

import datetime
import logging
import os
import shlex
import subprocess
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def build_borg_create_command(
    config: dict, service_name: str, paths: List[str], archive_name: str
) -> List[str]:
    """Build the borg create command as a list of arguments.

    Args:
        config: Configuration dictionary.
        service_name: Logical name of the service being backed up.
        paths: List of filesystem paths to include in the archive.
        archive_name: The final archive name (already formatted).

    Returns:
        A list of command arguments suitable for subprocess.run.
    """
    borg_cfg = config.get("borg", {})

    # Repository pieces
    storage = config.get("storage_box", {})
    user = storage.get("user")
    host = storage.get("host")
    port = storage.get("port")
    repo_path = storage.get("repo_path")

    if not all([user, host, port, repo_path]):
        logger.error(
            "Missing storage_box configuration (user, host, port, repo_path required)"
        )
        raise KeyError("Incomplete storage_box configuration for borg repository URL")

    # Construct repository URL: ssh://user@host:port/repo_path
    repo_url = f"ssh://{user}@{host}:{port}/{repo_path}"

    cmd: List[str] = ["borg", "create"]

    # Compression
    compression_map = {"zstd": "zstd", "none": "none"}
    comp = config.get("compression")
    if comp:
        comp_val = compression_map.get(comp, comp)
        cmd += ["--compression", comp_val]

    # Extra borg args
    extra_args = borg_cfg.get("extra_args") or []
    if isinstance(extra_args, str):
        # allow a single string of args
        extra_args = shlex.split(extra_args)
    cmd += extra_args

    # files_cache option
    files_cache = borg_cfg.get("files_cache")
    if files_cache:
        cmd += ["--files-cache", files_cache]

    # Repository::archive
    repo_and_archive = f"{repo_url}::{archive_name}"
    cmd.append(repo_and_archive)

    # Finally, the paths to backup
    cmd += paths

    logger.debug("Built borg create command: %s", cmd)
    return cmd


def run_borg_create(
    config: dict, service_name: str, paths: List[str]
) -> Tuple[bool, Optional[str]]:
    """Run borg create for the given service and paths.

    This will generate an archive name from the configured template, set up
    the SSH environment to use the configured key, execute borg create and
    return a tuple describing success and the archive name on success.

    Args:
        config: Configuration dictionary.
        service_name: Logical name of the service being backed up.
        paths: List of filesystem paths to include in the archive.

    Returns:
        (True, archive_name) on success, (False, None) on failure.
    """
    borg_cfg = config.get("borg", {})
    template = borg_cfg.get("archive_name_template", "{service}-{timestamp}")

    # Timestamp in UTC: YYYY-MM-DDTHH:MM:SS
    timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    archive_name = template.format(service=service_name, timestamp=timestamp)

    try:
        cmd = build_borg_create_command(config, service_name, paths, archive_name)
    except Exception:
        logger.exception("Failed to build borg create command")
        return False, None

    # Prepare environment with BORG_RSH to use the specified ssh key
    storage = config.get("storage_box", {})
    ssh_key = storage.get("ssh_key_path")
    host = storage.get("host")
    port = storage.get("port")
    user = storage.get("user")

    if not ssh_key:
        logger.error("ssh_key_path is not configured in storage_box")
        return False, None

    # Build BORG_RSH. Include port if provided and numeric.
    borg_rsh_parts = ["ssh", "-i", ssh_key, "-o", "StrictHostKeyChecking=accept-new"]
    if port:
        borg_rsh_parts += ["-p", str(port)]

    borg_rsh = " ".join(shlex.quote(p) for p in borg_rsh_parts)

    env = os.environ.copy()
    env["BORG_RSH"] = borg_rsh

    logger.info("Executing borg create: %s", " ".join(shlex.quote(p) for p in cmd))

    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        logger.debug("borg stdout: %s", proc.stdout)
        logger.debug("borg stderr: %s", proc.stderr)

        if proc.returncode == 0:
            logger.info("borg create succeeded: %s", archive_name)
            return True, archive_name
        else:
            logger.error(
                "borg create failed (code %s). See logs for details.", proc.returncode
            )
            return False, None

    except FileNotFoundError:
        logger.exception("borg executable not found in PATH")
        return False, None
    except Exception:
        logger.exception("Unexpected error while running borg create")
        return False, None
