# Backups Server — lightweight Borg backup orchestrator

Project summary
---------------
Backups Server is a small, opinionated tool that discovers important files and directories from services deployed with Docker Compose and stores incremental, deduplicated snapshots in remote Borg repositories over SSH. It supports per-service pre- and post-backup hooks, streams for large exports, and simple per-service local state to track the last successful archive. The project is aimed at two audiences:

- Operators: install, configure, and run backups with a reliable, auditable flow.
- Developers: understand the architecture, extend discovery or storage behavior, and write tests.

Quick start
-----------
1. Clone the repository and install dependencies:

```bash
git clone https://github.com/creep1ng/backups-server.git
cd backups-server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# or to install an entrypoint (optional):
pip install .
```

2. Show CLI help (installed entrypoint or via Python):

```bash
# if installed as console script (example name: backup-cli)
./backup-cli --help

# or run the script directly
python backup_tool.py --help
```

3. Run a full backup using the example config:

```bash
python backup_tool.py --config ./config.yaml.example backup
```

4. Run a backup for a single service (example):

```bash
python backup_tool.py --config ./config.yaml.example backup --service nextcloud
```

Configuration
-------------
This tool is configured with a YAML file. A full example is provided at [`config.yaml.example`](config.yaml.example:1). The top-level schema includes `storage_box`, `borg`, `compression` and a `services` list. A minimal snippet:

```yaml
version: 1
storage_box:
  host: "storage.example.com"
  port: 22
```

For the canonical schema and validation rules see the syntax reference: [`docs/configuration-syntax.md`](docs/configuration-syntax.md:1).

Storage box setup
-----------------
The remote Borg repository (the “storage box”) must be prepared before running backups. The operator guide covers SSH keys, repository initialization, encryption choices and unattended operation: see [`docs/storage-setup.md`](docs/storage-setup.md:1).

Usage and common workflows
-------------------------
- Show help: `python backup_tool.py --help` or `./backup-cli --help` (if installed).
- Backup all services: `python backup_tool.py --config ./config.yaml.example backup`.
- Backup single service: `python backup_tool.py --config ./config.yaml.example backup --service <service-name>`.

### Listing remote archives

The `list-remote` command lists archives stored in the remote Borg repository:

```bash
# List all archives (default TSV output, one per line)
python backup_tool.py --config ./config.yaml.example list-remote

# Filter by one or more services (repeatable)
python backup_tool.py --config ./config.yaml.example list-remote --service nextcloud
python backup_tool.py --config ./config.yaml.example list-remote --service nextcloud --service postgres

# Group archives by hostname (affects JSON output structure)
python backup_tool.py --config ./config.yaml.example list-remote --group-by hostname --json

# Output as JSON (schema version 1)
python backup_tool.py --config ./config.yaml.example list-remote --json
```

**Default output (TSV):** One archive per line with tab-separated fields: `archive`, `time_utc`, `hostname`, `service`, `id_short`. No headers or decorative output—designed for scripting and piping.

**JSON output (`--json`):** Structured output with schema version 1, including `generated_at`, `group_by`, `service_filter`, `archives` array, and optional `groups` object when `--group-by hostname` is specified. See [`remote_listing.py`](remote_listing.py:369) for the full schema.

**Filtering (`--service`):** Repeatable flag to filter archives by service name. Archives with unknown service names are excluded when filtering is active.

**Grouping (`--group-by`):** Supports `service` (default) or `hostname`. When set to `hostname` with `--json`, archives are additionally organized into a `groups` object keyed by hostname. Archives are always sorted deterministically: service → hostname → time_utc → archive name.

### Restoring a service

The `restore` command extracts a snapshot from the remote Borg repository into a local staging directory:

```bash
# Restore a specific snapshot by name
python backup_tool.py --config ./config.yaml.example restore --service nextcloud --snapshot nextcloud-2024-01-15T10:30:00 --staging-dir /tmp/restore

# Restore the latest known snapshot for a service
python backup_tool.py --config ./config.yaml.example restore --service nextcloud --latest --staging-dir /tmp/restore

# Force restore into a non-empty staging directory (bypasses empty check)
python backup_tool.py --config ./config.yaml.example restore --service nextcloud --latest --staging-dir /tmp/restore --force

# Force restore with automatic staging-to-production sync
# This extracts AND copies files to production path (requires restore_paths config)
python backup_tool.py --config ./config.yaml.example restore --service nextcloud --latest --staging-dir /tmp/restore --force-restore
```

**Required arguments:**
- `--service`: Name of the service to restore (must exist in configuration).
- `--staging-dir`: Local directory where the archive contents will be extracted.
- `--snapshot` OR `--latest`: Mutually exclusive. Specify either an exact archive name or request the latest available snapshot.

**Optional arguments:**
- `--force`: Allow restoring into a non-empty staging directory. Does NOT copy to production - only bypasses the staging directory emptiness check.
- `--force-restore`: Extract AND automatically copy files from staging to the configured production path. Requires `restore_paths` to be set in the service config. Overwrites existing content in the destination.

**restore_paths syntax options:**
- **Volume name only** (simplified): `"ollama_data"` - auto-resolves to Docker volume mountpoint
- **Volume with path**: `"ollama_data -> /custom/path"` - volume name with explicit production path  
- **Explicit mapping**: `"var/lib/... -> /production/path"` - full relative and absolute paths
- **$PRODUCTION_PATH**: `"relative/path -> $PRODUCTION_PATH"` - production equals staging path

**Staging directory semantics:**
- The staging directory is auto-created if it does not exist (including parent directories).
- If the directory exists and is not empty, the restore fails unless `--force` or `--force-restore` is specified.
- If the path exists but is not a directory, the restore fails regardless of flags.

**`--force` vs `--force-restore`:**
- `--force`: Only bypasses the non-empty staging directory check. Files are extracted to staging only. User must handle copying to production via post-restore hooks or manual steps.
- `--force-restore`: In addition to extracting to staging, automatically mirrors the extracted content to the production path defined in `restore_paths`, overwriting existing content. Requires `restore_paths` configuration.

**`--latest` resolution logic:**
1. **Prefer local state**: If a `last_success_archive` is recorded for the service in the local state store (`.backup-state/{service}.json`), use that archive name.
2. **Validate against remote**: Verify the local state archive still exists in the remote repository.
3. **Fallback to remote listing**: If local state is missing or the archive no longer exists, query `borg list` and select the newest archive by timestamp.
4. **Deterministic tie-breaking**: When multiple archives share the same timestamp, the lexicographically smaller archive name is selected.

**Restore hooks:**
- `restore_commands.pre`: Executed before `borg extract`. If any pre-hook fails, the restore aborts immediately.
- `restore_commands.post`: Executed after `borg extract`. Post-hooks run even if the extraction failed; failures are logged but do not affect the overall restore status.
- **Hook variables** (when `restore_paths` is configured):
  - `${STAGING_PATH}`: Resolved staging path (staging dir + relative path from archive)
  - `${PRODUCTION_PATH}`: Absolute production path from the mapping
  - These variables are both substituted in command strings AND exported to the subprocess environment.

**Example restore workflow with hooks:**
```yaml
services:
  - name: "nextcloud"
    compose_file: "/srv/nextcloud/docker-compose.yml"
    # Simplified: just use volume name - paths are auto-resolved
    restore_paths: "nextcloud_data"
    restore_commands:
      pre:
        # Stop the service before restoring
        - "docker compose -f /srv/nextcloud/docker-compose.yml down"
      post:
        # Restart the service after restore
        - "docker compose -f /srv/nextcloud/docker-compose.yml up -d"
        # Verify service is running
        - "docker compose -f /srv/nextcloud/docker-compose.yml ps"
```

**Alternative: Explicit path mapping:**
```yaml
services:
  - name: "nextcloud"
    compose_file: "/srv/nextcloud/docker-compose.yml"
    # Full explicit syntax
    restore_paths: "var/lib/docker/volumes/nextcloud_data/_data -> /var/lib/docker/volumes/nextcloud_data/_data"
    restore_commands:
      pre:
        - "docker compose -f /srv/nextcloud/docker-compose.yml down"
      post:
        - "docker compose -f /srv/nextcloud/docker-compose.yml up -d"
```

Hooks and state
- Pre-hooks are executed before the snapshot (fail-fast). Provide `backup_commands.pre` as a list of shell commands in the service config.
- Post-hooks are executed after the snapshot; they are attempted even if the borg snapshot failed. Provide `backup_commands.post` as a list of shell commands.
- The tool persists the last successful archive per service under a local state directory (`.backup-state/{service}.json`). See the developer docs: [`docs/implementation-guide.md`](docs/implementation-guide.md:1) and the state-store implementation details at [`docs/implementation-details/state-store.md`](docs/implementation-details/state-store.md:1).

Architecture and implementation references
----------------------------------------
High-level architecture and design rationale are documented at [`docs/architecture.md`](docs/architecture.md:1). Developer-focused, module-level guidance is available in the implementation guide index at [`docs/implementation-guide.md`](docs/implementation-guide.md:1). Key implementation details live under [`docs/implementation-details/`](docs/implementation-details/backup-flow.md:1) (for example, discovery and orchestration docs such as [`docs/implementation-details/docker-introspect.md`](docs/implementation-details/docker-introspect.md:1) and [`docs/implementation-details/backup-flow.md`](docs/implementation-details/backup-flow.md:1)).

Syntax and validation reference
-------------------------------
The authoritative configuration syntax and validation rules are in [`docs/configuration-syntax.md`](docs/configuration-syntax.md:1). Use `python -m pytest -q` to run tests that validate config behavior and orchestration logic.

Storage and state notes
-----------------------
- Local state: per-service JSON files are stored in `.backup-state/` and contain `last_success_archive` and `last_success_time`. See [`docs/implementation-details/state-store.md`](docs/implementation-details/state-store.md:1).
- Post-hook semantics: post-hooks are attempted even if the borg step fails; failures in post-hooks are logged and recorded but do not flip a failed borg run into success.

Troubleshooting and logs
------------------------
- Runtime logs: configure Python logging when running the CLI or inspect systemd logs if the tool is run as a service: `journalctl -u <service-name>`.
- Common diagnostics:
  - SSH troubleshooting: `ssh -vv backup@storage.example.com`
  - Verify repo connectivity: `borg list backup@storage.example.com:/srv/backups/repo`
  - Repo metadata: `borg info backup@storage.example.com:/srv/backups/repo`

Contributing, license and support
---------------------------------
Contributions are welcome. See the implementation guide for architecture and test guidance: [`docs/implementation-guide.md`](docs/implementation-guide.md:1). Run the test suite with:

```bash
python -m pytest -q
```

Please open issues for bugs or feature requests in the repository tracker. This project is provided under the repository’s license (see LICENSE file) and maintained by the project authors.

