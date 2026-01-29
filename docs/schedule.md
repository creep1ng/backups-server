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

## Phase 3 — Remote listing (1–2 days)

- Implement `list-remote` using `borg list --json` or `--format`. [`docs/schedule.md`](docs/schedule.md:23)
- Implement `--service` filters and grouping `--group-by hostname` using the `hostname` metadata. [`docs/schedule.md`](docs/schedule.md:24)
- Adjust output to be script-friendly (one line per snapshot or JSON).

## Phase 4 — Usable restore (2–4 days)

- Implement `borg extract` (restore to a staging directory).
- Implement `restore_commands.pre/post` hooks. [`docs/schedule.md`](docs/schedule.md:30)
- Add a `--latest` option (use local state and/or `borg list` to resolve the snapshot).

## Phase 5 — Robustness and hardening (2–3 days)

- Handle SIGINT/SIGTERM: save `last_step` and exit with appropriate exit codes.
- Retries with backoff for Borg/SSH operations.
- Permission validations (SSH key, sensitive paths).
- Deliver systemd unit/timer and deployment documentation. [`docs/schedule.md`](docs/schedule.md:38)
