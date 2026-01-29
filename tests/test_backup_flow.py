from __future__ import annotations

from typing import List, Tuple

import backup_flow


def _make_service_cfg(
    name: str, compose_file: str = "tests/fixtures/docker-compose.yml"
):
    return {"name": name, "compose_file": compose_file}


def test_pre_hook_failure_skips_borg(monkeypatch):
    cfg = {}
    svc = _make_service_cfg("svc")

    # Path discovery returns something reasonable
    monkeypatch.setattr(backup_flow, "discover_paths", lambda sc: ["/tmp/x"])

    # Pre-hooks fail
    monkeypatch.setattr(backup_flow, "run_hooks", lambda cmds, phase: False)

    # Borg should not be called; if it is, make it raise to fail the test
    monkeypatch.setattr(
        backup_flow,
        "run_borg_create",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("borg called")),
    )

    ok = backup_flow.backup_service(cfg, svc)
    assert ok is False


def test_borg_failure_runs_post_hook(monkeypatch):
    cfg = {}
    svc = _make_service_cfg("svc")

    monkeypatch.setattr(backup_flow, "discover_paths", lambda sc: ["/tmp/x"])

    # Pre-hooks succeed
    calls: List[Tuple[str, str]] = []

    def fake_run_hooks(cmds, phase):
        calls.append((phase, str(cmds)))
        return True

    monkeypatch.setattr(backup_flow, "run_hooks", fake_run_hooks)

    # Borg fails
    monkeypatch.setattr(
        backup_flow, "run_borg_create", lambda cfg, name, paths: (False, None)
    )

    # State update should not be called, but if it is, return True
    monkeypatch.setattr(backup_flow, "update_last_success_archive", lambda n, a: True)

    ok = backup_flow.backup_service(cfg, svc)
    assert ok is False
    # post hook was invoked (calls should include 'post')
    assert any(c[0] == "post" for c in calls)


def test_successful_backup_updates_state(monkeypatch):
    cfg = {}
    svc = _make_service_cfg("svc")

    monkeypatch.setattr(backup_flow, "discover_paths", lambda sc: ["/tmp/x"])
    monkeypatch.setattr(backup_flow, "run_hooks", lambda cmds, phase: True)

    # Borg succeeds and returns an archive name
    monkeypatch.setattr(
        backup_flow, "run_borg_create", lambda cfg, name, paths: (True, "svc-2020")
    )

    updated = {"v": False}

    def fake_update(name, archive):
        updated["v"] = True
        assert name == "svc"
        assert archive == "svc-2020"
        return True

    monkeypatch.setattr(backup_flow, "update_last_success_archive", fake_update)

    ok = backup_flow.backup_service(cfg, svc)
    assert ok is True
    assert updated["v"] is True
