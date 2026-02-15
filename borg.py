"""Borg operations module.

Provides helpers to build and run borg create commands for incremental
snapshots without intermediate tar files, and to list archives from
remote repositories.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import shlex
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

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


def build_repo_url(config: dict) -> str:
    """Build the Borg repository URL from config.

    Args:
        config: Configuration dictionary containing storage_box settings.

    Returns:
        The SSH repository URL (e.g., ssh://user@host:port/path).

    Raises:
        KeyError: If required storage_box configuration is missing.
    """
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
        return f"ssh://{user}@{host}:{port}{repo_path_str}"
    else:
        rel = repo_path_str.lstrip("./")
        return f"ssh://{user}@{host}:{port}/./{rel}"


def build_borg_environment(config: dict) -> dict:
    """Build the environment variables needed for Borg operations.

    This sets up BORG_RSH (SSH with configured key), BORG_PASSPHRASE,
    and non-interactive safeguards.

    Args:
        config: Configuration dictionary.

    Returns:
        Environment dict suitable for subprocess execution.

    Raises:
        ConfigValidationError: If required config is missing.
    """
    storage = config.get("storage_box", {})
    ssh_key = storage.get("ssh_key_path")
    host = storage.get("host")
    port = storage.get("port")
    user = storage.get("user")

    if not ssh_key:
        logger.error("ssh_key_path is not configured in storage_box")
        raise ConfigValidationError("ssh_key_path is not configured in storage_box")

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
        raise
    env["BORG_PASSPHRASE"] = passphrase

    return env


def _run_borg_command(
    cmd: List[str],
    env: dict,
    description: str = "borg",
) -> Tuple[int, str, str]:
    """Run a borg command and return results.

    Args:
        cmd: Command arguments list.
        env: Environment variables dict.
        description: Description for logging (e.g., 'borg create', 'borg list').

    Returns:
        Tuple of (return_code, stdout, stderr).
    """
    logger.info("Executing %s: %s", description, " ".join(shlex.quote(p) for p in cmd))

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for list operations
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error("%s timed out after 300 seconds", description)
        return -1, "", "Command timed out"
    except FileNotFoundError:
        logger.exception("borg executable not found in PATH")
        return -1, "", "borg executable not found in PATH"
    except Exception:
        logger.exception("Unexpected error while running %s", description)
        return -1, "", "Unexpected error"


def run_borg_list_archives(
    config: dict,
    service_filter: Optional[List[str]] = None,
) -> Tuple[bool, Optional[List[Dict[str, Any]]], Optional[str]]:
    """List archives from the remote Borg repository.

    This function attempts to use JSON output first, then falls back to
    deterministic TSV format parsing if JSON is not supported.

    Args:
        config: Configuration dictionary.
        service_filter: Optional list of service names to filter archives.

    Returns:
        Tuple of (success, archives_list, error_message).
        archives_list is a list of dicts with archive metadata.
    """
    repo_url = build_repo_url(config)
    env = build_borg_environment(config)

    # First try JSON output (preferred)
    cmd_json = ["borg", "list", "--json", repo_url]
    rc, stdout, stderr = _run_borg_command(cmd_json, env, "borg list --json")

    if rc == 0 and stdout:
        try:
            data = json.loads(stdout)
            if isinstance(data, dict) and "archives" in data:
                logger.debug("Successfully retrieved archives via JSON")
                return True, data.get("archives", []), None
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse JSON output: %s", exc)

    # JSON failed or not supported, fall back to TSV format
    logger.debug("JSON output not available, falling back to TSV format")

    # Use deterministic format: archive name, timestamp, hostname
    # Format: name\thostname\ttime
    tsv_cmd = [
        "borg",
        "list",
        "--format",
        "{name}\t{hostname}\t{time}\n",
        repo_url,
    ]
    rc, stdout, stderr = _run_borg_command(tsv_cmd, env, "borg list --format")

    if rc != 0:
        error_msg = stderr.strip() or f"borg list failed with code {rc}"
        logger.error("borg list failed: %s", error_msg)
        return False, None, error_msg

    # Parse TSV output
    archives = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            archives.append(
                {
                    "name": parts[0],
                    "hostname": parts[1],
                    "time": parts[2],
                }
            )
        elif len(parts) == 2:
            # Fallback if hostname missing
            archives.append(
                {
                    "name": parts[0],
                    "hostname": "",
                    "time": parts[1],
                }
            )
        elif len(parts) == 1:
            archives.append(
                {
                    "name": parts[0],
                    "hostname": "",
                    "time": "",
                }
            )

    logger.debug("Retrieved %d archives via TSV fallback", len(archives))
    return True, archives, None


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

    # Use shared helper to build repo URL
    repo_url = build_repo_url(config)

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


def build_borg_extract_command(
    config: dict, archive_name: str, target_dir: str
) -> List[str]:
    """Build the borg extract command for the requested archive."""

    repo_url = build_repo_url(config)
    repo_and_archive = f"{repo_url}::{archive_name}"

    cmd: List[str] = [
        "borg",
        "extract",
        "--target",
        target_dir,
        repo_and_archive,
    ]
    logger.debug("Built borg extract command: %s", cmd)
    return cmd


def run_borg_extract(config: dict, archive_name: str, target_dir: str) -> bool:
    """Execute borg extract for archive -> target_dir."""

    try:
        env = build_borg_environment(config)
    except ConfigValidationError:
        return False

    cmd = build_borg_extract_command(config, archive_name, target_dir)
    logger.info("Executing borg extract: %s", " ".join(shlex.quote(p) for p in cmd))

    try:
        rc, tail = _run_process_streaming_output(cmd, env)
        if rc == 0:
            logger.info("borg extract succeeded: %s", archive_name)
            return True
        logger.error("borg extract failed (code %s). Tail output:\n%s", rc, tail)
        return False
    except FileNotFoundError:
        logger.exception("borg executable not found in PATH")
        return False
    except Exception:
        logger.exception("Unexpected error while running borg extract")
        return False


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

    # Use shared helper to build environment
    try:
        env = build_borg_environment(config)
    except ConfigValidationError as exc:
        logger.error("Failed to build borg environment: %s", exc)
        return False, None

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
