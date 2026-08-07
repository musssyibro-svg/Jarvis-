"""
Does the test harness itself still work?

This exists because of a mistake made while writing it. conftest.py was
originally created at `backend/backend/tests/conftest.py` — one directory too
deep, because the shell's working directory was `backend/` at the time. pytest
found and ran every test anyway (pyproject sets `pythonpath = ["backend"]`, so
imports resolved), all 51 passed, and the report said green.

But the autouse `_no_network` fixture was never loaded. A test that quietly
reached Ollama or a freelance site would have passed silently, and the suite
would have looked exactly as green as it does now.

A fixture that stops working is invisible unless something checks it. This
checks it.
"""

import socket

import pytest


def test_outbound_connections_are_blocked():
    """The guard must raise, and say enough that you can find the caller."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(AssertionError, match="tried to open a network connection"):
        s.connect(("93.184.216.34", 80))  # example.com, never actually reached


def test_loopback_is_still_allowed():
    """
    Blocking loopback too would break anything that talks to a local test
    server. Connecting to a closed port must fail as a normal socket error, not
    as the guard's AssertionError.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    with pytest.raises((ConnectionRefusedError, OSError)) as excinfo:
        s.connect(("127.0.0.1", 9))  # discard port, nothing listening
    assert not isinstance(excinfo.value, AssertionError)
