"""Tests for the new list-remote CLI behavior."""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

import pytest

import backup_tool
import config_loader
from remote_listing import process_remote_archives, render_tsv

CONFIG_PATH = "tests/fixtures/valid_config.yaml"

ARCHIVE_FIXTURE_DATA = [
    {
        "name": "web-2026-02-12T10:00:00",
        "time": "2026-02-12T10:00:00",
        "hostname": "alpha",
        "id": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
    },
    {
        "name": "db-2026-02-12T09:00:00",
        "time": "2026-02-12T09:00:00",
        "hostname": "alpha",
        "id": "1111111111112222222222223333333333334444444444445555555555556666",
    },
    {
        "name": "web-2026-02-12T08:30:00",
        "time": "2026-02-12T08:30:00",
        "hostname": "beta",
        "id": "9999999999998888888888887777777777776666666666665555555555554444",
    },
    {
        "name": "db-2026-02-12T08:15:00",
        "time": "2026-02-12T08:15:00",
        "hostname": "beta",
        "id": "123456abcdef123456abcdef123456abcdef123456abcdef123456abcdef123456",
    },
]


def _raw_archives() -> list[dict[str, str]]:
    return [dict(record) for record in ARCHIVE_FIXTURE_DATA]


def _build_config() -> dict[str, object]:
    return {
        "version": 1,
        "storage_box": {
            "host": "example.com",
            "user": "backup",
            "ssh_key_path": "tests/fixtures/dummy_key",
            "repo_path": "/backups",
            "port": 22,
        },
        "borg": {
            "passphrase": "super-secret",
            "archive_name_template": "{service}-{timestamp}",
        },
        "services": [
            {"name": "web", "compose_file": "tests/fixtures/docker-compose.yml"},
            {"name": "db", "compose_file": "tests/fixtures/docker-compose.yml"},
        ],
    }


@pytest.fixture(autouse=True)
def patch_borg_list(monkeypatch) -> None:
    monkeypatch.setattr(config_loader, "load_config", lambda path: _build_config())
    monkeypatch.setattr(
        backup_tool,
        "run_borg_list_archives",
        lambda config, services: (True, _raw_archives(), None),
    )


def _capture_list_remote_output(args: list[str], capsys) -> tuple[int, str]:
    rc = backup_tool.main(["list-remote", *args, "--config", CONFIG_PATH])
    captured = capsys.readouterr()
    return rc, captured.out


def _expected_records(
    services: Optional[List[str]] = None, group_by: Optional[str] = None
) -> list:
    return process_remote_archives(
        _raw_archives(), _build_config(), services=services, group_by=group_by
    )


def _parse_generated_at(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_list_remote_basic_tsv_output(capsys) -> None:
    """Test basic TSV output with default ordering (service ASC, time DESC)."""
    rc, output = _capture_list_remote_output([], capsys)
    assert rc == 0
    expected = render_tsv(_expected_records())
    assert output.strip() == expected
    lines = output.strip().splitlines()
    assert len(lines) == len(_expected_records())
    for line in lines:
        assert line.count("\t") == 4


@pytest.mark.parametrize(
    ("flags", "services"),
    [
        (["--service", "web"], ["web"]),
        (["--service", "web", "--service", "db"], ["web", "db"]),
    ],
)
def test_list_remote_service_filters(flags, services, capsys) -> None:
    """Test filtering by single and multiple services."""
    rc, output = _capture_list_remote_output(flags, capsys)
    assert rc == 0
    expected = render_tsv(_expected_records(services=services))
    assert output.strip() == expected


def test_list_remote_group_by_hostname(capsys) -> None:
    """Test grouping by hostname changes ordering to (hostname ASC, service ASC, time DESC)."""
    rc, output = _capture_list_remote_output(["--group-by", "hostname"], capsys)
    assert rc == 0
    # When group_by=hostname, ordering is: hostname ASC, service ASC, time DESC, archive ASC
    records = _expected_records(group_by="hostname")
    assert output.strip() == render_tsv(records)


def test_list_remote_json_output(capsys) -> None:
    """Test JSON output with default grouping (service)."""
    rc, output = _capture_list_remote_output(["--json"], capsys)
    assert rc == 0
    payload = json.loads(output)
    expected_records = _expected_records()
    assert payload["schema_version"] == 1
    assert payload["group_by"] == "service"
    assert payload["service_filter"] is None
    assert payload["archives"] == [
        {
            "archive": record.archive,
            "time_utc": record.time_utc,
            "hostname": record.hostname,
            "service": record.service,
            "id": record.id,
            "id_short": record.id_short,
        }
        for record in expected_records
    ]
    assert "groups" not in payload
    _parse_generated_at(payload["generated_at"])


def test_list_remote_json_grouped_by_hostname(capsys) -> None:
    """Test JSON output with hostname grouping."""
    rc, output = _capture_list_remote_output(
        ["--json", "--group-by", "hostname"], capsys
    )
    assert rc == 0
    payload = json.loads(output)
    expected_records = _expected_records(group_by="hostname")
    assert payload["group_by"] == "hostname"
    assert payload["archives"] == [
        {
            "archive": record.archive,
            "time_utc": record.time_utc,
            "hostname": record.hostname,
            "service": record.service,
            "id": record.id,
            "id_short": record.id_short,
        }
        for record in expected_records
    ]
    assert payload.get("groups")
    for hostname, group_records in payload["groups"].items():
        group_raw = [r for r in expected_records if r.hostname == hostname]
        assert group_records == [
            {
                "archive": record.archive,
                "time_utc": record.time_utc,
                "hostname": record.hostname,
                "service": record.service,
                "id": record.id,
                "id_short": record.id_short,
            }
            for record in group_raw
        ]
