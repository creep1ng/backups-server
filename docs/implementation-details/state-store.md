# Local state persistence (`state_store.py`)

Purpose
- Provide a small, local per-service state store for recording the most recent successful archive identifier and associated metadata.

Storage location and schema
- State files are stored under `.backup-state/` in the current working directory. Each service has a file named `<service>.json`.
- Example JSON contents:

```json
{
  "last_success_archive": "myservice-2026-01-29T14:00:00",
  "last_success_time": "2026-01-29T14:00:05"
}
```

Public API
- `get_state_path(service_name: str) -> pathlib.Path` — returns and ensures the path to the per-service JSON file.
- `load_state(service_name: str) -> dict` — returns parsed state or `{}` when missing/invalid.
- `save_state(service_name: str, state: dict) -> bool` — writes `state` atomically and returns `True` on success.
- `update_last_success_archive(service_name: str, archive_name: str) -> bool` — convenience function that sets `last_success_archive` and `last_success_time` (UTC ISO string) and persists state.
- `get_last_success_archive(service_name: str) -> Optional[str]` — reads the persisted value or returns `None`.

Concurrency and atomicity
- Writes use an atomic replace pattern (write to a temp file in the same directory and `os.replace`), which is safe under typical POSIX semantics. Concurrent writers may override each other; the store is intentionally simple. If more advanced concurrency is needed, consider adding file locking or use a remote state store.

Operational notes
- State persistence is required for correct incremental decisions and for resumption behavior. A successful borg create with no persisted state is treated as a failure by the orchestration layer to ensure operators notice persistence problems.

