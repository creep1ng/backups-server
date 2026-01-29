from __future__ import annotations

import json
import os
from pathlib import Path

import state_store


def test_state_load_save_update(tmp_path):
    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)

        # Initially empty
        assert state_store.load_state("svc") == {}

        # Save some state
        s = {"foo": "bar"}
        ok = state_store.save_state("svc", s)
        assert ok is True

        # load it back
        loaded = state_store.load_state("svc")
        assert loaded.get("foo") == "bar"

        # update last_success_archive
        ok2 = state_store.update_last_success_archive("svc", "a-1")
        assert ok2 is True

        st = state_store.load_state("svc")
        assert st.get("last_success_archive") == "a-1"
        assert "last_success_time" in st

        # get_last_success_archive convenience
        assert state_store.get_last_success_archive("svc") == "a-1"

    finally:
        os.chdir(cwd)
