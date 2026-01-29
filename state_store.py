"""State persistence utilities for tracking backup state per service.

This module provides functions to read and write a small JSON file per
service under the .backup-state directory in the current working directory.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def get_state_path(service_name: str) -> Path:
    """Return the path to the state file for the given service.

    Ensures the .backup-state directory exists in the current working
    directory and returns the Path to `{service_name}.json` inside it.
    """
    base = Path.cwd() / ".backup-state"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        # If directory creation fails, re-raise after logging so callers
        # can handle the error as well.
        logger.exception("Failed to create state directory: %s", base)
        raise
    return base / f"{service_name}.json"


def load_state(service_name: str) -> Dict[str, object]:
    """Load and return the state dictionary for a service.

    Returns an empty dict if the state file doesn't exist or if the
    file contains invalid JSON (a warning is logged in that case).
    """
    path = get_state_path(service_name)
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in state file %s; returning empty state", path)
        return {}
    except Exception:
        logger.exception("Failed to read state file %s", path)
        return {}


def save_state(service_name: str, state: Dict[str, object]) -> bool:
    """Save the state dictionary to the service's JSON file atomically.

    Performs an atomic write by writing to a temporary file in the same
    directory and then replacing the destination file. Returns True on
    success and False on failure. Errors are logged.
    """
    dest = get_state_path(service_name)
    tmp_file = None
    try:
        # Ensure destination directory exists (get_state_path already does this)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Create temp file in same directory to allow atomic replace
        fd, tmp_path = tempfile.mkstemp(prefix=f".{service_name}", dir=str(dest.parent))
        tmp_file = Path(tmp_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            # If writing failed, remove temp file and re-raise
            try:
                tmp_file.unlink(missing_ok=True)
            except Exception:
                pass
            raise

        # Atomic replace
        os.replace(str(tmp_file), str(dest))
        return True
    except Exception:
        logger.exception("Failed to save state to %s", dest)
        return False


def update_last_success_archive(service_name: str, archive_name: str) -> bool:
    """Update the last_success_archive and last_success_time fields.

    Loads the current state for the service, updates the fields and saves
    the state. The last_success_time is the current UTC timestamp in ISO
    format. Returns True on success, False on failure.
    """
    state = load_state(service_name)
    state["last_success_archive"] = archive_name
    state["last_success_time"] = datetime.utcnow().isoformat()
    return save_state(service_name, state)


def get_last_success_archive(service_name: str) -> Optional[str]:
    """Return the last_success_archive value for the given service or None.

    If the state file doesn't exist or the key is not present, returns
    None.
    """
    state = load_state(service_name)
    val = state.get("last_success_archive")
    if isinstance(val, str):
        return val
    return None
