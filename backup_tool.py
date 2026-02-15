#!/usr/bin/env python3
"""
Command-line entrypoint for the backups tool (Phase 0 + Phase 1 + Phase 3).

Implements basic CLI commands as stubs and performs configuration
validation using the config loader.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

import backup_flow
import restore_flow
from borg import run_borg_list_archives
from config_loader import load_config
from errors import ConfigError
from remote_listing import (
    process_remote_archives,
    render_json,
    render_tsv,
)


def _exit_with_config_error(exc: ConfigError) -> None:
    print(f"Configuration error: {exc}", file=sys.stderr)
    sys.exit(1)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="backup_tool")
    # We purposely do not add a global --config to argparse so that the
    # option may appear before or after the subcommand. We'll manually
    # extract it from argv to provide flexible ordering.
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="Validate configuration file")

    backup_p = subparsers.add_parser(
        "backup", help="Run backup for a service or all services (stub)"
    )
    group = backup_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--service", help="Service name to backup")
    group.add_argument("--all", action="store_true", help="Backup all services")

    restore_p = subparsers.add_parser(
        "restore", help="Restore a service from a snapshot (stub)"
    )
    restore_p.add_argument("--service", required=True, help="Service name to restore")
    restore_p.add_argument(
        "--staging-dir",
        required=True,
        help="Directory where the archive will be extracted",
    )
    restore_p.add_argument(
        "--force",
        action="store_true",
        help="Allow restoring into a non-empty staging directory",
    )
    snapshot_group = restore_p.add_mutually_exclusive_group(required=True)
    snapshot_group.add_argument("--snapshot", help="Snapshot/archive name to restore")
    snapshot_group.add_argument(
        "--latest",
        action="store_true",
        help="Restore from latest snapshot",
    )

    list_p = subparsers.add_parser("list-remote", help="List remote archives")
    list_p.add_argument(
        "--service",
        action="append",
        dest="services",
        default=[],
        help="Filter by service name (can be specified multiple times)",
    )
    list_p.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of TSV",
    )
    list_p.add_argument(
        "--group-by",
        choices=("service", "hostname"),
        default="service",
        help="Group archives by specified key (default: service)",
    )

    # Normalize argv list
    argv_list = list(argv) if argv is not None else sys.argv[1:]

    # Extract --config manually so it can be placed anywhere in argv
    config_value: str | None = None
    cleaned_args: list[str] = []
    i = 0
    while i < len(argv_list):
        a = argv_list[i]
        if a == "--config":
            if i + 1 >= len(argv_list):
                print(
                    "backup_tool: error: argument --config: expected one argument",
                    file=sys.stderr,
                )
                return 2
            config_value = argv_list[i + 1]
            i += 2
            continue
        cleaned_args.append(a)
        i += 1

    try:
        args = parser.parse_args(cleaned_args)
    except SystemExit:
        # argparse already printed an error message
        return 2

    if not config_value:
        print(
            "backup_tool: error: the following arguments are required: --config",
            file=sys.stderr,
        )
        return 2

    config_path = Path(config_value)

    try:
        config = load_config(str(config_path))
    except ConfigError as e:
        _exit_with_config_error(e)
    except Exception as e:  # pragma: no cover - unexpected
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 2

    if args.command == "validate":
        print("Configuration is valid")
        return 0

    if args.command == "backup":
        results: object
        try:
            results = backup_flow.backup_all_services(config)
        except Exception as e:  # pragma: no cover - unexpected runtime error
            print(f"Unexpected error during backup: {e}", file=sys.stderr)
            return 2

        # Normalize results into iterable of (service, bool)
        service_results: list[tuple[str, bool]] = []

        if isinstance(results, dict):
            service_results = list(results.items())
        elif isinstance(results, (list, tuple)):
            # Could be list of (service, bool) or list of service names
            if all(isinstance(x, tuple) and len(x) >= 2 for x in results):
                service_results = [(str(k), bool(v)) for k, v in results]
            else:
                service_results = [(str(s), True) for s in results]
        elif isinstance(results, bool):
            # Only overall status provided; try to enumerate services from config
            try:
                services = list(config.get("services", {}).keys())  # type: ignore[attr-defined]
            except Exception:
                services = []
            service_results = [(s, bool(results)) for s in services]
        else:
            # Fallback: try to treat as mapping-like
            try:
                service_results = list(results.items())  # type: ignore[attr-defined]
            except Exception:
                service_results = []

        any_failed = False

        if service_results:
            for svc, ok in service_results:
                status = "success" if ok else "failed"
                print(f"{svc}: {status}")
                if not ok:
                    any_failed = True
        else:
            # No per-service information available; use overall boolean if possible
            if isinstance(results, bool):
                if results:
                    print("Backup completed")
                    return 0
                else:
                    print("Backup completed with failures")
                    return 1
            # Unknown result shape - consider this a failure
            print("Backup completed with failures")
            return 1

        if any_failed:
            print("Backup completed with failures")
            return 1

        print("Backup completed")
        return 0

    if args.command == "restore":
        if args.snapshot:
            archive_name = args.snapshot
        else:
            try:
                archive_name = restore_flow.resolve_latest_archive_name(
                    config, args.service
                )
            except restore_flow.RestoreError as exc:
                print(f"Failed to resolve latest archive: {exc}", file=sys.stderr)
                return 1

        try:
            ok = restore_flow.restore_service(
                config,
                args.service,
                archive_name,
                args.staging_dir,
                force=args.force,
            )
        except restore_flow.RestoreError as exc:
            print(f"Restore failed: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # pragma: no cover - unexpected runtime error
            print(f"Unexpected error during restore: {exc}", file=sys.stderr)
            return 2

        if not ok:
            print("Restore completed with failures", file=sys.stderr)
            return 1

        print("Restore completed")
        return 0

    if args.command == "list-remote":
        # Get service filter (convert to list if specified)
        services = args.services if args.services else None

        # Call borg list to get raw archives
        success, raw_archives, error = run_borg_list_archives(config, services)

        if not success:
            print(f"Failed to list archives: {error}", file=sys.stderr)
            return 1

        if raw_archives is None:
            print("No archives found", file=sys.stderr)
            return 1

        # Process the raw archives into normalized records
        processed = process_remote_archives(
            raw_archives=raw_archives,
            config=config,
            services=services,
            group_by=args.group_by,
        )

        # Render output
        if args.json:
            output = render_json(processed, args.group_by, services)
        else:
            output = render_tsv(processed)

        print(output)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
