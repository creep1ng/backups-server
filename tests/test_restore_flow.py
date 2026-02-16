from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import restore_flow


def _service_config(name: str) -> dict[str, object]:
    return {
        "services": [
            {
                "name": name,
                "compose_file": "tests/fixtures/docker-compose.yml",
                "restore_commands": {"pre": ["echo pre"], "post": ["echo post"]},
            }
        ],
        "storage_box": {
            "user": "u",
            "host": "h",
            "port": 22,
            "repo_path": "/repo",
        },
    }


def test_prepare_staging_dir_creates(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    restore_flow._prepare_staging_dir(staging, force=False)
    assert staging.exists() and staging.is_dir()


def test_prepare_staging_dir_refuses_non_empty(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "file").write_text("x")
    with pytest.raises(restore_flow.RestoreError) as exc_info:
        restore_flow._prepare_staging_dir(staging, force=False)
    assert "not empty" in str(exc_info.value)

    # Force mode bypasses the non-empty check.
    restore_flow._prepare_staging_dir(staging, force=True)


def test_restore_hooks_execute_in_order(monkeypatch, tmp_path: Path) -> None:
    cfg = _service_config("svc")
    calls: list[str] = []

    def fake_run_hooks(
        cmds: list[str], phase: str, substitutions=None, env=None
    ) -> bool:
        calls.append(phase)
        services = cast(list[dict[str, object]], cfg["services"])
        svc_config = services[0]
        restore_commands = cast(dict[str, list[str]], svc_config["restore_commands"])
        expected_cmds = restore_commands.get(phase, [])
        assert cmds == expected_cmds
        return True

    def fake_extract(*args, **kwargs) -> bool:
        calls.append("extract")
        return True

    monkeypatch.setattr(restore_flow, "run_hooks", fake_run_hooks)
    monkeypatch.setattr(restore_flow, "run_borg_extract", fake_extract)
    monkeypatch.setattr(restore_flow, "_prepare_staging_dir", lambda *_: None)

    ok = restore_flow.restore_service(cfg, "svc", "svc-2026", str(tmp_path / "stage"))
    assert ok is True
    assert calls == ["pre", "extract", "post"]


def test_pre_hook_failure_aborts_restore(monkeypatch, tmp_path: Path) -> None:
    cfg = _service_config("svc")
    called: list[str] = []

    def fake_run_hooks(
        cmds: list[str], phase: str, substitutions=None, env=None
    ) -> bool:
        called.append(phase)
        return phase != "pre"

    def fake_extract(*args, **kwargs) -> bool:
        raise AssertionError("borg extract should not run")

    monkeypatch.setattr(restore_flow, "run_hooks", fake_run_hooks)
    monkeypatch.setattr(restore_flow, "run_borg_extract", fake_extract)
    monkeypatch.setattr(restore_flow, "_prepare_staging_dir", lambda *_: None)

    assert (
        restore_flow.restore_service(cfg, "svc", "svc-2026", str(tmp_path / "stage"))
        is False
    )
    assert called == ["pre"]


def test_post_hook_failure_reports_error(monkeypatch, tmp_path: Path) -> None:
    cfg = _service_config("svc")
    calls: list[str] = []

    def fake_run_hooks(
        cmds: list[str], phase: str, substitutions=None, env=None
    ) -> bool:
        calls.append(phase)
        return phase != "post"

    def fake_extract(*args, **kwargs) -> bool:
        calls.append("extract")
        return True

    monkeypatch.setattr(restore_flow, "run_hooks", fake_run_hooks)
    monkeypatch.setattr(restore_flow, "run_borg_extract", fake_extract)
    monkeypatch.setattr(restore_flow, "_prepare_staging_dir", lambda *_: None)

    assert (
        restore_flow.restore_service(cfg, "svc", "svc-2026", str(tmp_path / "stage"))
        is False
    )
    assert calls == ["pre", "extract", "post"]


def test_resolve_latest_uses_state(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _service_config("svc")
    monkeypatch.setattr(
        restore_flow, "get_last_success_archive", lambda svc: "svc-state"
    )
    monkeypatch.setattr(
        restore_flow,
        "run_borg_list_archives",
        lambda cfg, services: (True, [{"archive": "svc-state"}], None),
    )
    monkeypatch.setattr(
        restore_flow,
        "process_remote_archives",
        lambda raw, config, services=None: [SimpleNamespace(archive="svc-state")],
    )

    assert restore_flow.resolve_latest_archive_name(cfg, "svc") == "svc-state"


def test_resolve_latest_falls_back_when_state_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _service_config("svc")
    monkeypatch.setattr(restore_flow, "get_last_success_archive", lambda svc: None)

    monkeypatch.setattr(
        restore_flow,
        "run_borg_list_archives",
        lambda cfg, services: (
            True,
            [{"archive": "svc-new"}, {"archive": "svc-old"}],
            None,
        ),
    )
    monkeypatch.setattr(
        restore_flow,
        "process_remote_archives",
        lambda raw, config, services=None: [
            SimpleNamespace(archive="svc-new"),
            SimpleNamespace(archive="svc-old"),
        ],
    )

    assert restore_flow.resolve_latest_archive_name(cfg, "svc") == "svc-new"


def test_resolve_latest_falls_back_when_state_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = _service_config("svc")
    monkeypatch.setattr(
        restore_flow, "get_last_success_archive", lambda svc: "svc-state"
    )

    monkeypatch.setattr(
        restore_flow,
        "run_borg_list_archives",
        lambda cfg, services: (True, [{"archive": "svc-new"}], None),
    )
    monkeypatch.setattr(
        restore_flow,
        "process_remote_archives",
        lambda raw, config, services=None: [SimpleNamespace(archive="svc-new")],
    )

    assert restore_flow.resolve_latest_archive_name(cfg, "svc") == "svc-new"


def test_resolve_latest_missing_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _service_config("svc")

    def raise_key_error(*args, **kwargs):
        raise KeyError

    monkeypatch.setattr(restore_flow, "run_borg_list_archives", raise_key_error)
    with pytest.raises(restore_flow.RestoreError) as exc_info:
        restore_flow.resolve_latest_archive_name(cfg, "svc")
    assert "Storage box configuration" in str(exc_info.value)


def test_resolve_latest_empty_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _service_config("svc")
    monkeypatch.setattr(restore_flow, "get_last_success_archive", lambda svc: None)
    monkeypatch.setattr(
        restore_flow,
        "run_borg_list_archives",
        lambda cfg, services: (True, [], None),
    )
    with pytest.raises(restore_flow.RestoreError) as exc_info:
        restore_flow.resolve_latest_archive_name(cfg, "svc")
    assert "contains no archives" in str(exc_info.value)


def test_restore_handles_missing_archive(monkeypatch, tmp_path: Path) -> None:
    cfg = _service_config("svc")
    calls: list[str] = []

    def fake_run_hooks(
        cmds: list[str], phase: str, substitutions=None, env=None
    ) -> bool:
        calls.append(phase)
        return True

    def fake_extract(*args, **kwargs) -> bool:
        calls.append("extract")
        return False

    monkeypatch.setattr(restore_flow, "run_hooks", fake_run_hooks)
    monkeypatch.setattr(restore_flow, "run_borg_extract", fake_extract)
    monkeypatch.setattr(restore_flow, "_prepare_staging_dir", lambda *_: None)

    assert (
        restore_flow.restore_service(cfg, "svc", "svc-missing", str(tmp_path / "stage"))
        is False
    )
    assert calls == ["pre", "extract", "post"]


def test_force_restore_requires_mapping(monkeypatch, tmp_path: Path) -> None:
    cfg = _service_config("svc")
    staging = tmp_path / "staging"
    staging.mkdir(parents=True)

    monkeypatch.setattr(
        restore_flow,
        "run_hooks",
        lambda cmds, phase, substitutions=None, env=None: True,
    )
    monkeypatch.setattr(restore_flow, "run_borg_extract", lambda *args, **kwargs: True)

    with pytest.raises(restore_flow.RestoreError) as exc_info:
        restore_flow.restore_service(
            cfg,
            "svc",
            "svc-2026",
            str(staging),
            force=True,
            force_restore=True,
        )
    assert "restore_paths" in str(exc_info.value)


def test_force_restore_mirrors_into_production(monkeypatch, tmp_path: Path) -> None:
    cfg = _service_config("svc")
    service = cast(list[dict[str, object]], cfg["services"])[0]
    relative = "backup/data"
    production = tmp_path / "prod"
    (production / "old").mkdir(parents=True)
    (production / "old" / "file").write_text("old")
    service["_restore_path_mapping"] = {
        "relative": relative,
        "production": str(production),
    }

    staging = tmp_path / "stage"
    staging_rel = staging / relative
    staging_rel.mkdir(parents=True)
    (staging_rel / "newfile").write_text("new")

    monkeypatch.setattr(
        restore_flow,
        "run_hooks",
        lambda cmds, phase, substitutions=None, env=None: True,
    )
    monkeypatch.setattr(restore_flow, "run_borg_extract", lambda *args, **kwargs: True)

    ok = restore_flow.restore_service(
        cfg,
        "svc",
        "svc-2026",
        str(staging),
        force=True,
        force_restore=True,
    )
    assert ok
    assert (production / "old").exists() is False
    assert (production / "newfile").read_text() == "new"


def test_restore_handles_invalid_staging_path(monkeypatch, tmp_path: Path) -> None:
    cfg = _service_config("svc")
    staging = tmp_path / "staging"
    staging.write_text("not a dir")

    monkeypatch.setattr(
        restore_flow,
        "run_hooks",
        lambda cmds, phase, substitutions=None, env=None: True,
    )
    called: list[str] = []

    def fake_extract(*args, **kwargs) -> bool:
        called.append("extract")
        return True

    monkeypatch.setattr(restore_flow, "run_borg_extract", fake_extract)

    assert restore_flow.restore_service(cfg, "svc", "svc-2026", str(staging)) is False
    assert called == []
