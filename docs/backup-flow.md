# Backup orchestration (`backup_flow.py`)

Purpose
- Provide a single place that orchestrates the backup sequence for one or more services. The CLI `backup` subcommand delegates to this module.

Public API
- `backup_service(config: dict, service_config: dict) -> bool`
  - Performs discovery, pre-hooks, borg create, post-hooks, and state update for a single service.
  - Returns `True` only when borg succeeded and `last_success_archive` was persisted successfully.
- `backup_all_services(config: dict) -> Dict[str, bool]`
  - Iterates the configured services and returns a mapping of service name -> success boolean.

Sequence and semantics

1. Path discovery: calls `docker_introspect.discover_paths(service_config)`.
2. Pre-hooks: calls `run_hooks(pre_cmds or [], 'pre')`. Failures abort the service run.
3. Borg create: calls `run_borg_create(config, service_name, paths)`.
4. Post-hooks: always called after the borg step via `run_hooks(post_cmds or [], 'post')` — attempted even on borg failure.
5. State update: if borg succeeded, call `update_last_success_archive(service_name, archive_name)`. If persistence fails, treat overall service as failed.

Testing notes
- Tests commonly monkeypatch the functions imported into `backup_flow` (e.g., `backup_flow.run_borg_create`) rather than patching implementations in other modules. This mirrors how the module imports functions at top-level and keeps tests focused on orchestration.

