> Assume a weekly iteration cadence with small, testable deliverables.

## Phase 0 — Preparation (0.5–1 day)

- Define the repository and minimal packaging (executable script + requirements).
- Agree on snapshot naming conventions (per-service) using placeholders or a fixed timestamp. [`docs/schedule.md`](docs/schedule.md:6)

## Phase 1 — Config + base CLI (1–2 days)

- Implement `validate` with YAML parsing and strict validation (early return).
- Implement the CLI with `backup`, `restore` (stub), and `list-remote` (stub).
- Manual tests: invalid YAML, missing fields, nonexistent paths.

## Phase 2 — Functional backup (2–4 days)

- Implement minimal path discovery (compose + env + extra_paths).
- Implement `backup_commands.pre/post` hooks. [`docs/schedule.md`](docs/schedule.md:17)
- Implement `borg create` for incremental snapshots without an intermediate tar file. [`docs/schedule.md`](docs/schedule.md:18)
- Persist `last_success_archive` in local state.

## Phase 3 — Remote listing (1–2 days) ✅ COMPLETE

- Implemented `list-remote` using `borg list --json` (preferred) with TSV fallback format. See [`remote_listing.py`](remote_listing.py:1) and [`borg.py`](borg.py:222).
- Implemented `--service` repeatable filter and `--group-by hostname` ordering using archive metadata.
- Output is script-friendly by default: one snapshot per line (TSV format with fields: archive, time_utc, hostname, service, id_short).
- JSON output mode available via `--json` flag with schema version 1 (see [`remote_listing.py`](remote_listing.py:16)).
- Archives are sorted deterministically: service → hostname → time_utc → archive name.

## Phase 4 — Usable restore (2–4 days)

- Implement `borg extract` (restore to a staging directory).
- Implement `restore_commands.pre/post` hooks. [`docs/schedule.md`](docs/schedule.md:30)
- Add a `--latest` option (use local state and/or `borg list` to resolve the snapshot).

## Phase 5 — Robustness and hardening (2–3 days)

- Handle SIGINT/SIGTERM: save `last_step` and exit with appropriate exit codes.
- Retries with backoff for Borg/SSH operations.
- Permission validations (SSH key, sensitive paths).
- Deliver systemd unit/timer and deployment documentation. [`docs/schedule.md`](docs/schedule.md:38)
