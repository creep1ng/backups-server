"""Integration tests for CLI entrypoint (updated for Phase 2).

These tests keep the existing subprocess-based validation tests but use
import/monkeypatch for the "backup" command so borg can be mocked easily.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import backup_flow
import backup_tool

SCRIPT = Path(__file__).parent.parent / "backup_tool.py"
FIXTURES = Path(__file__).parent / "fixtures"


def test_validate_success(tmp_path):
    # Ensure dummy referenced files exist
    (FIXTURES / "dummy_key").write_text("x")
    (FIXTURES / "docker-compose.yml").write_text("v: '3'")

    res = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate",
            "--config",
            str(FIXTURES / "valid_config.yaml"),
        ],
        capture_output=True,
    )
    assert res.returncode == 0
    assert b"Configuration is valid" in res.stdout


def test_validate_invalid(tmp_path):
    res = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate",
            "--config",
            str(FIXTURES / "invalid_syntax.yaml"),
        ],
        capture_output=True,
    )
    assert res.returncode == 1
    assert b"Configuration error" in res.stderr


def test_backup_all_success(monkeypatch) -> None:
    """When the backup flow reports overall success the CLI should exit 0."""
    monkeypatch.setattr(backup_flow, "backup_all_services", lambda cfg: True)
    rc = backup_tool.main(
        ["backup", "--all", "--config", "tests/fixtures/valid_config.yaml"]
    )
    assert rc == 0


def test_backup_all_failure(monkeypatch) -> None:
    """When the backup flow reports overall failure the CLI should exit 1."""
    monkeypatch.setattr(backup_flow, "backup_all_services", lambda cfg: False)
    rc = backup_tool.main(
        ["backup", "--all", "--config", "tests/fixtures/valid_config.yaml"]
    )
    assert rc == 1
