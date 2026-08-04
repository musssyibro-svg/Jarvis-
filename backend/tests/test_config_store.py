"""
Settings must save on a database that has never been initialised.

CI found this on a fresh checkout, and it could not reproduce on any machine
where Jarvis had been started even once — which is every dev machine.

`services/config.py` assumed `models.db.init_db()` had already run. Inside the
running backend that holds: main.py calls it at startup. Nothing else does —
tools/, the failure-injection harness and mcp_server.py all reach for config
directly.

On a database with no `settings` table, `set()` returned
`{"ok": False, "error": "no such table: settings"}` and almost every caller
ignores that dict. So the value looked saved and wasn't.

That is the "I set it, I saved it, nothing changed" bug that config.py exists
to prevent, occurring one layer below where it was being prevented.
"""

import importlib
import sys

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """A database file that no init_db() has ever touched."""
    monkeypatch.setenv("JARVIS_DB", str(tmp_path / "brand_new.db"))
    for mod in ("services.config", "models.db", "models"):
        monkeypatch.delitem(sys.modules, mod, raising=False)
    config = importlib.import_module("services.config")
    config.invalidate()
    yield config


def test_set_succeeds_on_an_uninitialised_database(fresh_db):
    out = fresh_db.set("search_engine", "baidu")
    assert out["ok"] is True, f"settings silently failed to save: {out}"


def test_the_value_is_actually_readable_afterwards(fresh_db):
    """ok:True is a claim. Reading it back is the evidence."""
    fresh_db.set("search_engine", "baidu")
    fresh_db.invalidate()
    assert fresh_db.get("search_engine") == "baidu"


def test_get_still_falls_back_when_nothing_is_stored(fresh_db):
    """A fresh install must still have working defaults, not empty strings."""
    assert fresh_db.get("ai_route_default") == "ollama"


def test_a_failed_write_reports_it_rather_than_pretending(fresh_db, monkeypatch):
    """
    The other half. If the write genuinely cannot happen — read-only disk,
    locked database — say so. A settings write that silently does nothing is
    worse than one that admits it failed.
    """

    def broken():
        raise RuntimeError("disk is read-only")

    monkeypatch.setattr(fresh_db, "conn", broken)
    out = fresh_db.set("search_engine", "bing")
    assert out["ok"] is False
    assert "read-only" in out["error"]
