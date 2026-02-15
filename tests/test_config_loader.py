"""Unit tests for config_loader.load_config"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from config_loader import get_borg_passphrase, load_config
from errors import ConfigSyntaxError, ConfigValidationError

FIXTURES = Path(__file__).parent / "fixtures"


def _write_dummy_files():
    # Ensure files referenced in fixtures exist for tests
    dkey = FIXTURES / "dummy_key"
    dcompose = FIXTURES / "docker-compose.yml"
    dkey.write_text("dummy")
    dcompose.write_text(
        textwrap.dedent("""
        version: '3'
    """)
    )


def test_valid_minimal_config(tmp_path):
    _write_dummy_files()
    cfg = load_config(str(FIXTURES / "valid_config.yaml"))
    assert cfg["version"] == 1
    assert "storage_box" in cfg
    assert isinstance(cfg["services"], list)


def test_get_borg_passphrase(tmp_path):
    _write_dummy_files()
    cfg = load_config(str(FIXTURES / "valid_config.yaml"))
    assert get_borg_passphrase(cfg) == cfg["borg"]["passphrase"]


def test_invalid_yaml_syntax():
    with pytest.raises(ConfigSyntaxError):
        load_config(str(FIXTURES / "invalid_syntax.yaml"))


def test_missing_borg_passphrase(tmp_path):
    _write_dummy_files()
    with pytest.raises(ConfigValidationError):
        load_config(str(FIXTURES / "no_borg_passphrase.yaml"))


def test_empty_borg_passphrase(tmp_path):
    _write_dummy_files()
    with pytest.raises(ConfigValidationError):
        load_config(str(FIXTURES / "empty_passphrase.yaml"))


def test_missing_required_fields():
    with pytest.raises(ConfigValidationError):
        load_config(str(FIXTURES / "missing_fields.yaml"))


def test_invalid_types(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("version: 'one'\nstorage_box: {}\nservices: []\n")
    with pytest.raises(ConfigValidationError):
        load_config(str(p))


def test_nonexistent_paths(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text(
        "version: 1\nstorage_box:\n  host: h\n  user: u\n  ssh_key_path: /does/not/exist\n  repo_path: /repo\nservices:\n  - name: s\n    compose_file: /nope\n"
    )
    with pytest.raises(ConfigValidationError):
        load_config(str(p))


def test_duplicate_service_names(tmp_path):
    p = tmp_path / "dup.yaml"
    p.write_text(
        "version: 1\nstorage_box:\n  host: h\n  user: u\n  ssh_key_path: tests/fixtures/dummy_key\n  repo_path: /r\nservices:\n  - name: a\n    compose_file: tests/fixtures/docker-compose.yml\n  - name: a\n    compose_file: tests/fixtures/docker-compose.yml\n"
    )
    # create referenced files
    (Path("tests/fixtures/dummy_key")).write_text("x")
    (Path("tests/fixtures/docker-compose.yml")).write_text("v: '3'")
    with pytest.raises(ConfigValidationError):
        load_config(str(p))


def test_invalid_compression_algorithm(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "version: 1\nstorage_box:\n  host: h\n  user: u\n  ssh_key_path: tests/fixtures/dummy_key\n  repo_path: /r\ncompression:\n  algorithm: lz4\nservices:\n  - name: s\n    compose_file: tests/fixtures/docker-compose.yml\n"
    )
    (Path("tests/fixtures/dummy_key")).write_text("x")
    (Path("tests/fixtures/docker-compose.yml")).write_text("v: '3'")
    with pytest.raises(ConfigValidationError):
        load_config(str(p))
