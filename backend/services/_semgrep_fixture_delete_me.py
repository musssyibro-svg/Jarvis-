"""
TEMPORARY. Exists to prove jarvis-url-opened-without-check actually fires.

A Semgrep rule with a malformed pattern reports zero findings, which looks
exactly like passing — that has already happened in this repo once. Semgrep
can't be installed in the dev container (the proxy blocks PyPI), so the only
honest way to test the rule is to push something it must catch and watch CI go
red. This file is deleted in the very next commit.
"""


def open_it(url: str) -> None:
    import webbrowser

    webbrowser.open(url)
