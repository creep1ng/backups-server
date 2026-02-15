"""Path discovery helpers for Docker compose backed services.

This module provides a minimal implementation to discover host paths that
should be included in backups based on a service configuration and the
corresponding Docker Compose file.

The main entrypoint is :func:`discover_paths`.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Dict, Iterable, List, Optional

import yaml

from errors import ConfigValidationError

logger = logging.getLogger(__name__)

# Cache for resolved named volumes to avoid repeated docker calls
_named_volume_cache: Dict[str, Optional[str]] = {}


def _resolve_candidate_path(candidate: str, compose_dir: str) -> str:
    """Resolve a candidate host path to an absolute path.

    If the candidate is an absolute path it is returned as-is (but
    abspath-normalised). If it is relative, it is interpreted relative to
    the directory containing the compose file.

    Args:
        candidate: The raw host path string as extracted from compose.
        compose_dir: Directory containing the compose file.

    Returns:
        Absolute, normalized path string.
    """
    if os.path.isabs(candidate):
        return os.path.abspath(candidate)
    # Treat relative paths as relative to compose file directory
    return os.path.abspath(os.path.join(compose_dir, candidate))


def _resolve_named_volume(volume_name: str, compose_project: str = "") -> Optional[str]:
    """Resolve a named Docker volume to its host mount path.

    Uses `docker volume inspect` to get the mountpoint of a named volume.
    Results are cached to avoid repeated Docker CLI calls.

    Args:
        volume_name: The name of the Docker volume (may be short name or with prefix).
        compose_project: Optional compose project name to try as prefix.

    Returns:
        The absolute host mount path, or None if the volume cannot be resolved.
    """
    # Build list of volume names to try (short name first, then with project prefix)
    names_to_try = [volume_name]
    if compose_project and not volume_name.startswith(compose_project):
        names_to_try.append(f"{compose_project}_{volume_name}")

    for name in names_to_try:
        if name in _named_volume_cache:
            cached = _named_volume_cache[name]
            if cached:
                return cached
            # If cached as None, try other names
            continue

        try:
            result = subprocess.run(
                ["docker", "volume", "inspect", "-f", "{{.Mountpoint}}", name],
                capture_output=True,
                text=True,
                check=True,
            )
            mountpoint = result.stdout.strip()
            if mountpoint:
                # Cache all tried names as this one worked
                for n in names_to_try:
                    _named_volume_cache[n] = mountpoint
                logger.debug("Resolved named volume %s to %s", name, mountpoint)
                return mountpoint
        except subprocess.CalledProcessError as e:
            logger.debug("Volume %s not found, trying next", name)
        except FileNotFoundError:
            logger.warning("Docker CLI not found - cannot resolve named volumes")
            break
        except Exception as e:
            logger.warning("Error resolving named volume %s: %s", name, e)
            break

    # Cache failures
    for name in names_to_try:
        _named_volume_cache[name] = None
    return None


def _extract_from_volume_string(volume: str) -> Optional[str]:
    """Extract the host path or volume name from a volume string.

    Examples:
      - './data:/app/data' -> './data'
      - '/abs/path:/container:ro' -> '/abs/path'
      - 'named_volume:/container' -> 'named_volume' (for resolution)

    Args:
        volume: The compose volume string.

    Returns:
        The host path portion, volume name, or None.
    """
    # Split on ':' but only up to 2 splits so we capture formats with mode
    parts = volume.split(":", 2)
    if not parts:
        return None
    # If the first part looks like a host path (absolute or relative path
    # starting with '.'), return it. Otherwise it's a named volume.
    host = parts[0]
    if host.startswith("/") or host.startswith("."):
        return host
    # Treat as potential named volume
    return host


def _iter_volume_host_paths(compose_data: Dict, compose_dir: str) -> Iterable[str]:
    """Yield host paths discovered from compose services.*.volumes.

    Handles both the short string form and the long dictionary form used by
    newer compose schemas (with 'type' and 'source' keys). Also handles
    named Docker volumes by resolving them via Docker CLI.

    Extracts the compose project name from the compose file directory to
    resolve volume names with the correct project prefix.
    """
    # Extract project name from compose directory (default project name is dir name)
    compose_project = os.path.basename(os.path.abspath(compose_dir))

    services = compose_data.get("services") or {}
    for svc_name, svc in services.items():
        volumes = svc.get("volumes") or []
        for vol in volumes:
            # short string form
            if isinstance(vol, str):
                candidate = _extract_from_volume_string(vol)
                if candidate:
                    # Check if it's a bind mount (absolute or relative path)
                    if candidate.startswith("/") or candidate.startswith("."):
                        yield _resolve_candidate_path(candidate, compose_dir)
                    elif candidate.startswith("~"):
                        # Handle tilde paths (e.g., ~/.memos)
                        yield os.path.expanduser(candidate)
                    else:
                        # It's a named volume - resolve via Docker CLI
                        mountpoint = _resolve_named_volume(candidate, compose_project)
                        if mountpoint:
                            yield mountpoint
                        else:
                            logger.warning(
                                "Could not resolve named volume '%s' for service '%s' - "
                                "volume may not exist or Docker may not be available",
                                candidate,
                                svc_name,
                            )
                continue

            # dict form: expect keys like 'type', 'source', 'target'
            if isinstance(vol, dict):
                vol_type = vol.get("type")
                source = vol.get("source") or (vol.get("bind") or {}).get("source")

                # Handle named volumes (type='volume' with source)
                if vol_type == "volume" and source:
                    mountpoint = _resolve_named_volume(source, compose_project)
                    if mountpoint:
                        yield mountpoint
                    else:
                        logger.warning(
                            "Could not resolve named volume '%s' for service '%s' - "
                            "volume may not exist or Docker may not be available",
                            source,
                            svc_name,
                        )
                # Handle bind-type volumes
                elif source and vol_type == "bind":
                    if isinstance(source, str):
                        if source.startswith("~"):
                            # Handle tilde paths
                            yield os.path.expanduser(source)
                        elif source.startswith("/") or source.startswith("."):
                            yield _resolve_candidate_path(str(source), compose_dir)
                continue


def discover_paths(service_config: Dict) -> List[str]:
    """Discover host paths related to a service.

    The returned list always includes the compose_file path found in
    ``service_config``. It also includes any ``env_files`` and ``extra_paths``
    entries, and attempts to parse the compose YAML to extract host-side
    bind mounts from ``services.*.volumes``.

    All returned paths are absolute, deduplicated and in the order they were
    discovered. Missing paths are logged as warnings but do not stop
    processing.

    Args:
        service_config: A dictionary describing a service. Expected keys used
            are ``compose_file`` (str), and optional ``env_files`` and
            ``extra_paths`` (iterables of str).

    Raises:
        ConfigValidationError: If the compose file exists but cannot be
            parsed as YAML.

    Returns:
        A list of absolute host paths (strings), de-duplicated.
    """
    compose_file = service_config.get("compose_file")
    if not compose_file:
        raise ConfigValidationError("service_config is missing 'compose_file'")

    discovered: List[str] = []
    seen = set()

    # Compose dir used to resolve relative paths
    compose_dir = os.path.dirname(os.path.abspath(compose_file))

    def _add(path: str) -> None:
        abs_path = os.path.abspath(path)
        if abs_path not in seen:
            seen.add(abs_path)
            discovered.append(abs_path)
            if not os.path.exists(abs_path):
                logger.warning("Discovered path does not exist: %s", abs_path)

    # Always include the compose file itself (may not exist)
    _add(compose_file)

    # Include env_files and extra_paths if present
    for key in ("env_files", "extra_paths"):
        entries = service_config.get(key) or []
        for e in entries:
            # Resolve relative entries relative to compose file directory
            resolved = (
                _resolve_candidate_path(e, compose_dir) if isinstance(e, str) else None
            )
            if resolved:
                _add(resolved)

    # Attempt to parse the compose file to extract bind mount host paths.
    try:
        with open(compose_file, "r", encoding="utf-8") as fh:
            compose_data = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        # Compose file missing - this is not a parsing error but we already
        # added the compose file above and logged existence there.
        compose_data = {}
    except yaml.YAMLError as exc:
        raise ConfigValidationError(
            f"Failed to parse compose file '{compose_file}': {exc}"
        )

    # Extract host paths from volumes
    for host_path in _iter_volume_host_paths(compose_data, compose_dir):
        _add(host_path)

    return discovered
