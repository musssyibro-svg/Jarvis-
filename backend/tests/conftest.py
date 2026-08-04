"""
Shared pytest fixtures.

Why this directory exists at all: `verification/` LOOKS like a test suite and
is not. Those files are manual scripts with a run() entry point that need a
live backend on :8000, a live Ollama, and sometimes a real Windows desktop.
Collecting them produces a wall of red that means "the server isn't running",
which teaches you to ignore red. pytest is pointed here instead
(see pyproject.toml testpaths).

Everything in here must run offline, on any OS, with no backend, no Ollama and
no display — otherwise it can't gate a commit.
"""

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """
    A unit test that quietly reaches Ollama or a freelance site is not a unit
    test — it's a flaky integration test that passes on your machine and fails
    in CI. Anything that tries gets a loud failure naming the caller.
    """
    import socket

    real = socket.socket.connect

    def guard(self, address, *a, **kw):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host in ("127.0.0.1", "::1", "localhost"):
            return real(self, address, *a, **kw)
        raise AssertionError(
            f"A unit test tried to open a network connection to {host}. "
            f"Mock it, or move the test to verification/."
        )

    monkeypatch.setattr(socket.socket, "connect", guard)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """A throwaway jarvis.db, so tests never touch the user's real one."""
    monkeypatch.setenv("JARVIS_DB", str(tmp_path / "test.db"))
    return tmp_path / "test.db"


def pytest_configure(config):
    os.environ.setdefault("JARVIS_TESTING", "1")
