# Borg wrapper and connection semantics (`borg.py`)

Purpose
- Provide a small wrapper around `borg create` that builds the correct repository URL, applies compression and extra args from configuration, and ensures Borg uses the configured SSH identity.

Public API
- `build_borg_create_command(config: dict, service_name: str, paths: List[str], archive_name: str) -> List[str]`
  - Constructs the argument list for `borg create` including compression option and any `borg.extra_args` from the config.

- `run_borg_create(config: dict, service_name: str, paths: List[str]) -> Tuple[bool, Optional[str]]`
  - Generates an archive name from the configured template, sets `BORG_RSH` to use the configured SSH key and port, executes borg, and returns `(True, archive_name)` on success or `(False, None)` on failure.

Repository URL and SSH
- Repository URL format used: `ssh://<user>@<host>:<port>/<repo_path>`.
- `BORG_RSH` is set to `ssh -i <ssh_key> -p <port> -o StrictHostKeyChecking=accept-new` so Borg uses the identity file and reasonable host-key handling by default.

Return codes and logging
- `run_borg_create` returns `True` only when the `borg create` subprocess exits with code `0`. stdout/stderr are logged (INFO/DEBUG) to aid diagnosis. Any exceptions during execution are caught and logged; the function returns `(False, None)` on error.

Operational notes
- Ensure the SSH key file referenced in the configuration is readable by the process and has strict permissions (e.g., 0600).
- Running `borg create` directly on many large paths may be IO-bound; monitor system load and consider offloading compression CPU limits via Borg options when configured.

