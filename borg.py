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
import time
from typing import List, Optional, Tuple

from config_loader import get_borg_passphrase
from errors import ConfigValidationError

logger = logging.getLogger(__name__)


def _run_process_streaming_output(
    cmd: List[str],
    env: dict,
) -> Tuple[int, str]:
    """Run a subprocess while streaming its combined stdout/stderr to logs.

    Why this exists:
    - `subprocess.run(..., capture_output=True)` buffers *all* output until the
      process exits. Borg (and the underlying ssh) often prints progress and
      may print interactive prompts to stderr. Buffering can make long-running
      operations appear "stuck" and can also hide prompts.

    Returns:
        (return_code, combined_output_tail)
    """

    # Merge stderr into stdout so we don't deadlock and so prompts/progress are
    # visible in a single stream.
    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    output_tail: List[str] = []
    tail_limit = 200  # lines
    last_line_ts = time.time()

    assert proc.stdout is not None  # for type checkers
    for line in proc.stdout:
        last_line_ts = time.time()
        line = line.rstrip("\n")
        if not line:
            continue
        logger.info("[borg] %s", line)
        output_tail.append(line)
        if len(output_tail) > tail_limit:
            output_tail = output_tail[-tail_limit:]

    rc = proc.wait()
    runtime = time.time() - (last_line_ts)  # not exact runtime, but fine for logs
    logger.debug("borg process exited rc=%s (last_output_age=%.1fs)", rc, runtime)
    return rc, "\n".join(output_tail)


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

    # Construct repository URL.
    #
    # Borg's ssh URL forms are sensitive:
    # - Absolute repo path:   ssh://user@host:port/absolute/path
    # - Relative-to-home:     ssh://user@host:port/./relative/path
    #
    # Our config uses `storage_box.repo_path`. If it starts with '/', treat it
    # as an absolute remote path. Otherwise, treat it as relative to the
    # remote user's home and normalize to '/./...'.
    repo_path_str = str(repo_path)
    if repo_path_str.startswith("/"):
        # Avoid accidental double-slashes like '...:23//home/backup'.
        repo_url = f"ssh://{user}@{host}:{port}{repo_path_str}"
    else:
        rel = repo_path_str.lstrip("./")
        repo_url = f"ssh://{user}@{host}:{port}/./{rel}"

    cmd: List[str] = ["borg", "create"]

    # Compression
    compression_map = {"zstd": "zstd", "none": "none", "auto": "auto"}
    comp = config.get("compression")
    if comp:
        if isinstance(comp, dict):
            algorithm = comp.get("algorithm")
            level = comp.get("level")
            if algorithm:
                comp_val = compression_map.get(algorithm, algorithm)
                if level is not None and comp_val not in {"none", "auto"}:
                    comp_val = f"{comp_val},{level}"
                cmd += ["--compression", comp_val]
        else:
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
    now = datetime.datetime.utcnow()
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    logger.debug(
        "Formatting archive name with template=%r service=%r timestamp=%r now=%r",
        template,
        service_name,
        timestamp,
        now,
    )
    try:
        archive_name = template.format(
            service=service_name, timestamp=timestamp, now=now
        )
    except KeyError as exc:
        logger.exception(
            "Archive name template has missing key: %s (template=%r)",
            exc,
            template,
        )
        raise

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

    # Build BORG_RSH.
    #
    # Important: ensure ssh is non-interactive. If ssh needs to prompt (unknown
    # host key, encrypted key passphrase, etc.), it may block waiting for input
    # and the prompt may not be visible depending on how output is captured.
    borg_rsh_parts = [
        "ssh",
        "-i",
        ssh_key,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=20",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=3",
    ]
    if port:
        borg_rsh_parts += ["-p", str(port)]

    borg_rsh = " ".join(shlex.quote(p) for p in borg_rsh_parts)

    env = os.environ.copy()
    env["BORG_RSH"] = borg_rsh

    # --- NON-INTERACTIVE SAFEGUARDS ---
    # Borg can prompt interactively in several scenarios:
    # 1) Repo "relocated" from a different URL (e.g., path changed)
    # 2) Unknown host key (should be handled by SSH StrictHostKeyChecking)
    # 3) Repository integrity issues
    # Force non-interactive (fail instead of prompt) for unattended operation.
    env["BORG_RELOCATED_REPO_ACCESS_IS_OK"] = "yes"
    env["BORG_HOST_KEY_IS_OK"] = "yes"

    try:
        passphrase = get_borg_passphrase(config)
    except ConfigValidationError as exc:
        logger.error("Failed to retrieve borg passphrase: %s", exc)
        return False, None
    env["BORG_PASSPHRASE"] = passphrase

    logger.info("Executing borg create: %s", " ".join(shlex.quote(p) for p in cmd))

    try:
        rc, tail = _run_process_streaming_output(cmd, env)
        if rc == 0:
            logger.info("borg create succeeded: %s", archive_name)
            return True, archive_name

        logger.error("borg create failed (code %s). Tail output:\n%s", rc, tail)
        return False, None

    except FileNotFoundError:
        logger.exception("borg executable not found in PATH")
        return False, None
    except Exception:
        logger.exception("Unexpected error while running borg create")
        return False, None
