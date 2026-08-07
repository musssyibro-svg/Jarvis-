"""
Jarvis must survive a machine with no display.

CI caught this and local testing could not. `import pyautogui` on a headless
Linux runner does not raise ImportError — it pulls in mouseinfo, which runs
`Display(os.environ['DISPLAY'])` at module scope and raises
`KeyError: 'DISPLAY'`. The guard was `except ImportError`, so importing
desktop_agent CRASHED rather than degrading.

Five failure-injection scenarios and the whole import check went down with it.

It never reproduced locally because pyautogui simply wasn't installed here, so
the ImportError path worked perfectly. "Installed but unusable" is a different
state from "not installed", and only one of them was handled.

CLAUDE.md: a missing optional dependency is a SKIP with an install hint, not a
failure. Installed-but-unusable deserves the same treatment — and a DIFFERENT
hint, because telling someone to install what they already have sends them
hunting for a bug that isn't there.
"""

import importlib
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

# What the real pyautogui does with no DISPLAY, reduced to its essentials.
_HEADLESS_STUB = "import os\n_ = os.environ['DISPLAY']\n"


@pytest.fixture
def headless(tmp_path, monkeypatch):
    """Put stub modules on sys.path that fail the way a headless machine does."""
    for name in ("pyautogui", "pygetwindow", "mss"):
        (tmp_path / f"{name}.py").write_text(_HEADLESS_STUB, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delenv("DISPLAY", raising=False)
    for mod in list(sys.modules):
        if mod.startswith(
            ("agents.desktop_agent", "agents.vision_agent", "pyautogui", "pygetwindow", "mss")
        ):
            monkeypatch.delitem(sys.modules, mod, raising=False)
    yield


def test_desktop_agent_imports_without_a_display(headless):
    da = importlib.import_module("agents.desktop_agent")
    assert da.HAS_PYAUTOGUI is False
    assert da.HAS_WINDOWS is False


def test_vision_agent_imports_without_a_display(headless):
    va = importlib.import_module("agents.vision_agent")
    assert va.HAS_MSS is False


def test_input_refuses_with_a_reason_that_is_true(headless):
    """
    "Run: pip install pyautogui" is actively wrong here — it IS installed. The
    message must name the real cause instead.
    """
    da = importlib.import_module("agents.desktop_agent")
    r = da.type_text("hello")
    assert r["success"] is False
    err = r["error"].lower()
    assert "installed but" in err or "display" in err or "keyerror" in err, (
        f"the error blames the wrong thing: {r['error']!r}"
    )
    assert "pip install pyautogui" not in err, (
        "told the user to install a package they already have"
    )


def test_a_genuinely_missing_package_still_says_install_it(tmp_path, monkeypatch):
    """The other half: a real ImportError must still produce the install hint."""
    (tmp_path / "sitecustomize_block.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for mod in list(sys.modules):
        if mod.startswith("agents.desktop_agent"):
            monkeypatch.delitem(sys.modules, mod, raising=False)

    real_import = __import__

    def blocked(name, *a, **kw):
        if name in ("pyautogui", "pygetwindow"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", blocked)
    da = importlib.import_module("agents.desktop_agent")
    monkeypatch.undo()

    assert da.HAS_PYAUTOGUI is False
    assert "pip install pyautogui" in da.type_text("hello")["error"]
