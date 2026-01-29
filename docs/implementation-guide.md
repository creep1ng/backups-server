## Recommended structure (lean)

- `backup_tool.py` (CLI entrypoint)
- `config_loader.py` (load + validate YAML, early return)
- `backup_flow.py` (orchestrates backup/restore/list)
- `docker_introspect.py` (discover paths from compose)
- `commands.py` (pre/post hooks, using safe subprocess calls)
- `borg.py` (wrapper for Borg invocations: create/list/extract)
- `state_store.py` (minimal local state per service, JSON)
- `retry.py` (simple retries with backoff)
- `errors.py` (custom exceptions)

## CLI (argparse)

Commands:

- `backup --service <name>|--all`
- `restore --service <name> --snapshot <archive_name>|--latest`
- `list-remote [--service <name>] [--format text|json] [--group-by service|hostname]`
- `validate`

For “list services by host”:

- `list-remote --group-by hostname` groups by the `hostname` metadata exposed by `borg list` for archives. [`docs/implementation-guide.md`](docs/implementation-guide.md:24)
- Alternative (if you prefer not to rely on hostname): group by archive name prefix; this guide recommends hostname because Borg exposes it directly. [`docs/implementation-guide.md`](docs/implementation-guide.md:25)

## Borg wrapper (safe subprocess)

### Create incremental snapshot

Base invocation: `borg create [options] ARCHIVE [PATH...]`. [`docs/implementation-guide.md`](docs/implementation-guide.md:31)

Recommendation: build `ARCHIVE` as `ssh://USER@HOST:PORT/ABS_REPO_PATH::{service}-{timestamp}` (or the equivalent format supported by your remote repo). [`docs/implementation-guide.md`](docs/implementation-guide.md:33)

### Streaming for dumps (avoid out-of-space)

Two Borg-supported routes:

- Pass `-` as a PATH to read from `stdin` and store a file named `stdin` inside the archive. [`docs/implementation-guide.md`](docs/implementation-guide.md:39)
- Prefer: `--content-from-command` so Borg runs the command and will fail the archive creation if the command fails (avoids truncated archives). [`docs/implementation-guide.md`](docs/implementation-guide.md:40)

Practical implementation:

- In YAML, use `backup_commands.pre` for light-weight operations (e.g., flush, quiesce writes).
- For large dumps, define `streams:` (see YAML spec) and in `backup_flow` add those entries as `--content-from-command` arguments to the `borg create` invocation. [`docs/implementation-guide.md`](docs/implementation-guide.md:45)

### Remote snapshot listing

`borg list` lists repository contents or archives. [`docs/implementation-guide.md`](docs/implementation-guide.md:49)

For frontends and stable parsing:

- `borg list --json <REPO>` (valid when listing a repository) to obtain JSON output. [`docs/implementation-guide.md`](docs/implementation-guide.md:53)
- Or `borg list --format ... <REPO>` for stable text output; when listing archives you can format entries like `"{archive} {time} [{id}]"`. [`docs/implementation-guide.md`](docs/implementation-guide.md:54)

Also, `borg list` exposes keys such as `archive`, `id`, `time`, `hostname` and `username` when listing repository archives, enabling `--group-by hostname`. [`docs/implementation-guide.md`](docs/implementation-guide.md:56)

## Path discovery (compose + env)

Backups must include compose files, `.env`, volumes and bind mounts. [`docs/implementation-guide.md`](docs/implementation-guide.md:60)

Minimal implementation:

- Parse the compose YAML and extract `services.*.volumes`.
- Identify binds (they take the form `host_path:container_path[:mode]`) and add the host path to `PATH...`.
- Docker named volumes do not always map to a stable host path; in the first version you may require bind mounts for critical data or resolve named volumes using `docker volume inspect` (via subprocess).

## Local state and resumption

Requirement: if interrupted, it should be possible to resume a job from the last completed step. [`docs/implementation-guide.md`](docs/implementation-guide.md:70)

Lean implementation:

- One JSON per service in `/var/lib/backup_tool/state/<service>.json` containing:
    - `last_success_archive`
    - `last_step` (simple enum: `pre_hooks`, `borg_create`, `post_hooks`)
    - `updated_at`

## systemd (service + timer)

Requirement: run via systemd unit and timer. [`docs/implementation-guide.md`](docs/implementation-guide.md:81)

Minimum deliverable:

- `backup_tool.service`: runs `backup_tool.py backup --all`.
- `backup_tool.timer`: schedule (e.g., daily), with `Persistent=true` so it runs after downtime.
