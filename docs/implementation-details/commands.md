# Hook execution primitives (`commands.py`)

This document describes the hook execution primitives used by the backup flow.

Purpose
- Run configured shell commands before and after a backup to quiesce services, export data, or perform cleanup.

Public API
- `run_command(command: str, timeout: int = 300) -> Tuple[int, str, str]`
  - Runs a shell command with `subprocess.run(shell=True, capture_output=True, text=True)`.
  - Returns `(return_code, stdout, stderr)`; on exception returns `(-1, "", str(exception))`.

- `run_hooks(commands: List[str], phase: str) -> bool`
  - Executes `commands` sequentially, logging outputs and stopping at first non-zero exit code (fail-fast).
  - `phase` is a string used for logging: typically `'pre'` or `'post'`.
  - Returns `True` when all commands succeed, `False` otherwise.
  - Empty lists are accepted and treated as no-ops (return `True`). The production code calls `run_hooks(... or [], phase)` so tests can reliably monkeypatch `run_hooks` and observe invocations.

Behavior and semantics
- Pre-hooks: called before the borg create step. Their failure aborts the backup for that service.
- Post-hooks: called after borg create (attempted even when borg fails). Post-hook failures are logged but do not flip a failed borg run into success.

Security and operational notes
- Commands are executed with `shell=True` by design in Phase 2 to allow straightforward string-based commands in configuration. This is convenient but increases risk of shell injection; configuration should be trusted or migrated to a structured form in a future refactor.
- Hook stdout/stderr are logged at DEBUG level. Configure logging appropriately to capture diagnostics.

