"""
Configuration loader and validator for backups tool.

Loads YAML configuration files and validates them strictly according to
the schema defined in docs/configuration-syntax.md.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from errors import ConfigSyntaxError, ConfigValidationError

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_NAME = "config.yaml"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / DEFAULT_CONFIG_NAME

DEFAULT_ARCHIVE_TEMPLATE = "{service}-{now:%Y-%m-%dT%H:%M:%S}"


def _ensure_type(value: Any, expected_type: type, path: str) -> None:
    if not isinstance(value, expected_type):
        raise ConfigValidationError(f"{path} must be of type {expected_type.__name__}")


def _file_exists_readable(path: str | Path, path_desc: str) -> None:
    p = Path(path)
    if not p.exists():
        raise ConfigValidationError(f"{path_desc} '{p}' does not exist")
    if not os.access(p, os.R_OK):
        raise ConfigValidationError(f"{path_desc} '{p}' is not readable")


def _resolve_config_path(path: Optional[str]) -> Path:
    if path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return (PROJECT_ROOT / candidate).resolve()
    return DEFAULT_CONFIG_PATH


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load and validate configuration YAML file.

    Parameters
    ----------
    path:
        Path to YAML configuration file.

    Returns
    -------
    dict
        Validated configuration dictionary.

    Raises
    ------
    ConfigSyntaxError
        If the YAML cannot be parsed.
    ConfigValidationError
        If the configuration fails validation checks.
    """
    config_path = _resolve_config_path(path)
    _file_exists_readable(config_path, "config file")

    try:
        with config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except yaml.YAMLError as e:
        raise ConfigSyntaxError(f"YAML syntax error: {e}")

    if raw is None:
        raise ConfigValidationError("Configuration is empty")

    if not isinstance(raw, dict):
        raise ConfigValidationError(
            "Top-level configuration must be a mapping/dictionary"
        )

    # version
    if "version" not in raw:
        raise ConfigValidationError("Missing required 'version' field")
    if not isinstance(raw["version"], int) or raw["version"] != 1:
        raise ConfigValidationError("'version' must be integer 1")

    # storage_box
    if "storage_box" not in raw:
        raise ConfigValidationError("Missing required 'storage_box' section")
    storage = raw["storage_box"]
    if not isinstance(storage, dict):
        raise ConfigValidationError("'storage_box' must be a mapping/dictionary")

    for key in ("host", "user", "ssh_key_path", "repo_path"):
        if key not in storage:
            raise ConfigValidationError(f"'storage_box' missing required field '{key}'")

    _ensure_type(storage["host"], str, "storage_box.host")
    _ensure_type(storage["user"], str, "storage_box.user")
    _ensure_type(storage["ssh_key_path"], str, "storage_box.ssh_key_path")
    _ensure_type(storage["repo_path"], str, "storage_box.repo_path")

    # port optional
    if "port" in storage:
        if not isinstance(storage["port"], int):
            raise ConfigValidationError("storage_box.port must be an integer")
    else:
        storage["port"] = 22

    # ssh key must exist and be readable
    _file_exists_readable(storage["ssh_key_path"], "ssh_key_path")

    # borg
    borg = raw.get("borg", {})
    if borg is None:
        borg = {}
    if not isinstance(borg, dict):
        raise ConfigValidationError("'borg' must be a mapping/dictionary if provided")

    archive_template = borg.get("archive_name_template", DEFAULT_ARCHIVE_TEMPLATE)
    if not isinstance(archive_template, str):
        raise ConfigValidationError("borg.archive_name_template must be a string")
    borg["archive_name_template"] = archive_template

    extra_args = borg.get("extra_args")
    if extra_args is not None:
        if not isinstance(extra_args, list) or not all(
            isinstance(x, str) for x in extra_args
        ):
            raise ConfigValidationError("borg.extra_args must be a list of strings")

    files_cache = borg.get("files_cache")
    if files_cache is not None and not isinstance(files_cache, str):
        raise ConfigValidationError(
            "borg.files_cache must be a string path if provided"
        )

    # compression
    compression = raw.get("compression", {})
    if compression is None:
        compression = {}
    if not isinstance(compression, dict):
        raise ConfigValidationError(
            "'compression' must be a mapping/dictionary if provided"
        )

    algorithm = compression.get("algorithm")
    if algorithm is not None:
        if not isinstance(algorithm, str):
            raise ConfigValidationError("compression.algorithm must be a string")
        if algorithm not in {"zstd", "none"}:
            raise ConfigValidationError(
                "compression.algorithm must be one of {zstd, none}"
            )

    level = compression.get("level")
    if level is not None and not isinstance(level, int):
        raise ConfigValidationError("compression.level must be an integer if provided")

    # services
    if "services" not in raw:
        raise ConfigValidationError("Missing required 'services' list")
    services = raw["services"]
    if not isinstance(services, list) or len(services) == 0:
        raise ConfigValidationError("'services' must be a non-empty list")

    seen_names: set[str] = set()
    for idx, svc in enumerate(services):
        svc_path = f"services[{idx}]"
        if not isinstance(svc, dict):
            raise ConfigValidationError(f"{svc_path} must be a mapping/dictionary")

        if "name" not in svc:
            raise ConfigValidationError(f"{svc_path} missing required 'name'")
        if not isinstance(svc["name"], str):
            raise ConfigValidationError(f"{svc_path}.name must be a string")
        if svc["name"] in seen_names:
            raise ConfigValidationError(f"Duplicate service name '{svc['name']}'")
        seen_names.add(svc["name"])

        if "compose_file" not in svc:
            raise ConfigValidationError(f"{svc_path} missing required 'compose_file'")
        if not isinstance(svc["compose_file"], str):
            raise ConfigValidationError(f"{svc_path}.compose_file must be a string")
        # compose file must exist
        _file_exists_readable(svc["compose_file"], f"{svc_path}.compose_file")

        for list_field in ("env_files", "extra_paths"):
            if list_field in svc:
                if not isinstance(svc[list_field], list) or not all(
                    isinstance(x, str) for x in svc[list_field]
                ):
                    raise ConfigValidationError(
                        f"{svc_path}.{list_field} must be a list of strings"
                    )

        for cmd_group in ("backup_commands", "restore_commands"):
            if cmd_group in svc:
                if not isinstance(svc[cmd_group], dict):
                    raise ConfigValidationError(
                        f"{svc_path}.{cmd_group} must be a mapping with 'pre' and/or 'post' lists"
                    )
                for phase in ("pre", "post"):
                    if phase in svc[cmd_group]:
                        if not isinstance(svc[cmd_group][phase], list) or not all(
                            isinstance(x, str) for x in svc[cmd_group][phase]
                        ):
                            raise ConfigValidationError(
                                f"{svc_path}.{cmd_group}.{phase} must be a list of strings"
                            )

        streams = svc.get("streams")
        if streams is not None:
            if not isinstance(streams, list):
                raise ConfigValidationError(f"{svc_path}.streams must be a list")
            for sidx, stream in enumerate(streams):
                if not isinstance(stream, dict):
                    raise ConfigValidationError(
                        f"{svc_path}.streams[{sidx}] must be a mapping/dictionary"
                    )
                if "name" not in stream or "command" not in stream:
                    raise ConfigValidationError(
                        f"{svc_path}.streams[{sidx}] missing 'name' or 'command'"
                    )
                if not isinstance(stream["name"], str):
                    raise ConfigValidationError(
                        f"{svc_path}.streams[{sidx}].name must be a string"
                    )
                if not isinstance(stream["command"], list) or not all(
                    isinstance(x, str) for x in stream["command"]
                ):
                    raise ConfigValidationError(
                        f"{svc_path}.streams[{sidx}].command must be a list of strings"
                    )

    # All checks passed; return normalized config
    normalized = raw.copy()
    normalized["borg"] = borg
    normalized["compression"] = compression
    normalized["storage_box"] = storage
    normalized["_config_path"] = str(config_path)

    # Validate Borg passphrase now that config path is known
    get_borg_passphrase(normalized)
    return normalized


def get_borg_passphrase(config: Dict[str, Any]) -> str:
    borg_cfg = config.get("borg", {})
    passphrase = borg_cfg.get("passphrase")
    config_path = config.get("_config_path") or str(DEFAULT_CONFIG_PATH)

    if passphrase is None:
        raise ConfigValidationError(f"Missing borg.passphrase in '{config_path}'")
    if not isinstance(passphrase, str) or not passphrase.strip():
        raise ConfigValidationError(
            f"borg.passphrase in '{config_path}' must be a non-empty string"
        )
    return passphrase
