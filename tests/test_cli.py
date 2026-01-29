"""Integration tests for CLI entrypoint stubs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

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


def test_stubs_return_message(tmp_path):
    (FIXTURES / "dummy_key").write_text("x")
    (FIXTURES / "docker-compose.yml").write_text("v: '3'")

    # backup stub
    res = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "backup",
            "--all",
            "--config",
            str(FIXTURES / "valid_config.yaml"),
        ],
        capture_output=True,
    )
    assert res.returncode == 0
    assert b"Not implemented yet" in res.stdout

    # restore stub
    res = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "restore",
            "--service",
            "web",
            "--latest",
            "--config",
            str(FIXTURES / "valid_config.yaml"),
        ],
        capture_output=True,
    )
    assert res.returncode == 0
    assert b"Not implemented yet" in res.stdout

    # list-remote stub
    res = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "list-remote",
            "--config",
            str(FIXTURES / "valid_config.yaml"),
        ],
        capture_output=True,
    )
    assert res.returncode == 0
    assert b"Not implemented yet" in res.stdout
