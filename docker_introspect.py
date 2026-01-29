"""Path discovery helpers for Docker compose backed services.

This module provides a minimal implementation to discover host paths that
should be included in backups based on a service configuration and the
corresponding Docker Compose file.

The main entrypoint is :func:`discover_paths`.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Iterable, List, Optional

import yaml

from errors import ConfigValidationError

logger = logging.getLogger(__name__)


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


def _extract_from_volume_string(volume: str) -> Optional[str]:
    """Extract the host path from a volume string if present.

    Examples:
      - './data:/app/data' -> './data'
      - '/abs/path:/container:ro' -> '/abs/path'
      - 'named_volume:/container' -> None (named volume)

    Args:
        volume: The compose volume string.

    Returns:
        The host path portion or None when the volume is a named volume.
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
    return None


def _iter_volume_host_paths(compose_data: Dict, compose_dir: str) -> Iterable[str]:
    """Yield host paths discovered from compose services.*.volumes.

    Handles both the short string form and the long dictionary form used by
    newer compose schemas (with 'type' and 'source' keys).
    """
    services = compose_data.get("services") or {}
    for svc_name, svc in services.items():
        volumes = svc.get("volumes") or []
        for vol in volumes:
            # short string form
            if isinstance(vol, str):
                host = _extract_from_volume_string(vol)
                if host:
                    yield _resolve_candidate_path(host, compose_dir)
                continue

            # dict form: expect keys like 'type', 'source', 'target'
            if isinstance(vol, dict):
                vol_type = vol.get("type")
                source = vol.get("source") or vol.get("bind")
                # Only consider bind-type volumes or sources that look like
                # host paths. Named volumes have no host source.
                if source and (
                    vol_type == "bind"
                    or isinstance(source, str)
                    and (source.startswith("/") or source.startswith("."))
                ):
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
