"""
"It opened QQ the first time but never again."

The root cause, found by inspection after the focus fix didn't fully explain it:
_app_visible() matched process names and window titles by SUBSTRING. So:

    asked for "notepad"  ->  matched  notepad++.exe
    asked for "qq"       ->  matched  qqbrowser.exe
    asked for "code"     ->  matched  codemeter.exe
    asked for "qq"       ->  matched  an Edge tab titled "QQ音乐下载 - Edge"

open_app() returns "already open" the instant that says yes. So a browser tab
that merely MENTIONED the app made Jarvis skip the launch, report success, and
then screenshot whatever happened to be in front — which is exactly what the
user saw: "no visible unread messages" from a window that was never QQ.
"""

import pytest

from agents import desktop_agent as da


class _FakeProc:
    def __init__(self, name):
        self.info = {"name": name}


@pytest.fixture
def processes(monkeypatch):
    """Pretend a specific set of processes is running."""

    def _set(names):
        monkeypatch.setattr(
            da.psutil, "process_iter", lambda *a, **k: [_FakeProc(n) for n in names]
        )

    return _set


@pytest.mark.parametrize(
    "asked_for,running,why",
    [
        ("notepad", "notepad++.exe", "Notepad++ is a different program"),
        ("qq", "qqbrowser.exe", "QQ Browser is not QQ"),
        ("code", "codemeter.exe", "CodeMeter is not VS Code"),
        ("word", "wordpad.exe", "WordPad is not Word"),
    ],
)
def test_a_similarly_named_program_is_not_the_app(asked_for, running, why, processes):
    processes([running])
    assert da._running_process_for(asked_for) is None, why


@pytest.mark.parametrize(
    "asked_for,running",
    [
        ("notepad", "notepad.exe"),
        ("qq", "qq.exe"),
        ("edge", "msedge.exe"),
        ("calculator", "calculatorapp.exe"),
        ("wechat", "weixin.exe"),
        ("vscode", "code.exe"),
    ],
)
def test_the_real_app_is_still_found(asked_for, running, processes):
    """The fix must not make detection so strict that nothing matches."""
    processes([running])
    assert da._running_process_for(asked_for) == running


def test_a_window_title_alone_is_not_evidence(monkeypatch, processes):
    """
    Anyone can open a web page called "QQ音乐下载". A title is not the app.
    On Windows, detection is process-only.
    """
    processes([])
    monkeypatch.setattr(da, "HAS_WINDOWS", True)
    # raising=False: pygetwindow isn't importable here, so `gw` is unbound —
    # which is itself the headless case the module is built to survive.
    monkeypatch.setattr(
        da,
        "gw",
        type(
            "gw",
            (),
            {
                "getAllTitles": staticmethod(
                    lambda: ["QQ音乐下载 - Edge", "Microsoft Word Tutorial"]
                )
            },
        ),
        raising=False,
    )
    monkeypatch.setattr(da.os, "name", "nt")
    assert da._app_visible("qq") is False
    assert da._app_visible("word") is False


def test_already_running_actually_raises_the_window(monkeypatch, processes):
    """
    open_app used to return {"method": "focus", "verified": True} without
    focusing OR verifying. Both claims were false, and everything after it
    acted on the wrong window.
    """
    processes(["qq.exe"])
    calls = []
    monkeypatch.setattr(
        da, "focus_window", lambda app, *a, **k: (calls.append(app), {"success": True})[1]
    )

    out = da.open_app("qq")
    assert calls == ["qq"], "claimed to focus the window and didn't"
    assert out["verified"] is True
    assert "qq.exe" in out["resolved"]


def test_unraisable_window_is_reported_not_hidden(monkeypatch, processes):
    """If it can't be brought to the front, say so — the next step is at risk."""
    processes(["qq.exe"])
    monkeypatch.setattr(da, "focus_window", lambda *a, **k: {"success": False})

    out = da.open_app("qq")
    assert out["verified"] is False
    assert "warning" in out
    assert "wrong window" in out["warning"]
