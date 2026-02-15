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

