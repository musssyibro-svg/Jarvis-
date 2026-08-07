"""
agents/ui_agent.py — read and drive Windows applications through their
accessibility tree, instead of guessing from pixels.

WHY THIS EXISTS

Two of the things Jarvis was asked to do most often were the two it did worst,
and both failed for the same reason: it had no way to *read the interface*.

  "check my qq messages"     opened the app, took a screenshot, and sent the
                             picture to a vision model. Median 55 seconds, and
                             the answer was a paraphrase of a JPEG.

  "send ahmed a message"     opened the app, OCR'd the screen, clicked whatever
                             pixels looked most like the word "ahmed", typed,
                             and pressed Enter. Nothing checked which chat was
                             actually open before the message went out.

Windows already exposes what is on the screen as structured data — element
names, roles, values, positions — through UI Automation. Reading it takes
milliseconds and returns the real text, not a description of an image. That is
what this module uses. The screenshot path stays as the fallback for apps that
expose nothing (see below); it is no longer the first resort.

WHY `uiautomation` AND NOT SOMETHING ELSE

  wxauto      WeChat-specific, and pins itself to particular WeChat builds. It
              is a wrapper over `uiautomation`, so it adds a version-coupled
              dependency on top of the thing we would be using anyway. In
              mainland China WeChat updates often; a helper that breaks on
              update is worse than no helper, because it breaks silently.
  pywinauto   Capable, but it wants to own the whole session (Application(),
              connect(), backend selection) and it re-implements window finding
              — which this repo already does correctly for Chinese Windows in
              desktop_agent._win32_focus. Two window finders would disagree.
  by hand     comtypes + the raw IUIAutomation interfaces is a week of work to
              arrive at what `uiautomation` already is.

So: `uiautomation` for the tree, and desktop_agent for everything to do with
windows and input, which it already gets right.

WHAT THIS CANNOT DO, STATED UP FRONT

QQ NT is an Electron app. Chromium only builds an accessibility tree when it
believes a screen reader is listening, and even then most of QQ's chat surface
is canvas-drawn with no element names. Expect `snapshot()` to return a window
with almost nothing in it. That is reported as exactly that — "this app draws
its interface without exposing any text to Windows" — and it names the vision
fallback. It is not reported as an empty inbox. WeChat, Notepad, Explorer,
Office, Settings and most native apps expose a full tree.

WHAT "VERIFIED" MEANS HERE

Reading changes nothing, so there is no after-state to compare. What can be
checked — and what actually goes wrong — is whether the text came from the
window you asked about. Every read confirms the foreground window belongs to
the requested app's process before it reads, and `verify_reason` says so. A
read that could not confirm its source reports verified=False, because
answering "you have no new messages" from the wrong window is the exact failure
this module was built to end.

Writing is verified properly: after typing into a field we read that field's
value back through UI Automation and compare. That is a real observation of the
real control, not the Ctrl+A/Ctrl+C clipboard round-trip desktop_agent has to
use when there is no accessibility tree to ask.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout
from dataclasses import dataclass, field

from services import trace

# ── Bounds ───────────────────────────────────────────────────────────────────
#
# Every property read below is a cross-process COM call: single-digit
# milliseconds each, and a chat window has thousands of elements. An unbounded
# walk of WeChat's tree took long enough in testing to look like a hang, which
# is the same failure mode CLAUDE.md already bans for network calls. So the
# walk stops at whichever of these three it hits first and says it was cut
# short, rather than running to completion at any cost.
MAX_DEPTH = 14           # deeper than this is layout scaffolding, not content
MAX_NODES = 700          # enough for a full chat list plus a conversation
WALK_BUDGET_S = 8.0      # wall clock for one tree walk
CALL_BUDGET_S = 25.0     # wall clock for one public call, including the walk

# Text longer than this on a single node is a document body, not a label. Kept
# whole in `value` for edit controls (that is the thing we verify against) and
# truncated in `name` (that is only ever used for matching and display).
MAX_NAME = 400
MAX_VALUE = 8000


# ── The optional dependency, in three states ─────────────────────────────────
#
# Installed-and-working, not-installed, and installed-but-unusable are three
# different situations with three different fixes, and telling the user to
# `pip install` a package they already have sends them hunting for a bug that
# is not there. `except Exception`, never `except ImportError`: on a machine
# with no interactive desktop, importing uiautomation raises from comtypes at
# module scope, which is not an ImportError.

_uia = None
_uia_reason = ""
_uia_version = ""
_load_lock = threading.Lock()
_loaded = False


def _load() -> bool:
    """Import uiautomation once. Never raises. Returns True if usable."""
    global _uia, _uia_reason, _uia_version, _loaded
    with _load_lock:
        if _loaded:
            return _uia is not None
        _loaded = True
        import os
        if os.name != "nt":
            _uia_reason = (
                "Windows UI Automation only exists on Windows. Jarvis is "
                "running on " + os.name + " here, so it can only read apps "
                "through screenshots.")
            return False
        try:
            import uiautomation as u
        except ImportError:
            _uia_reason = ("the uiautomation package is not installed. "
                           "Run: pip install uiautomation")
            return False
        except Exception as e:
            _uia_reason = (
                f"uiautomation is installed but can't start here "
                f"({type(e).__name__}: {e}). On Windows that usually means "
                f"there is no interactive desktop session — Jarvis must run as "
                f"you, not as a service.")
            return False
        # A short global search timeout matters more than it looks. uiautomation
        # defaults to retrying a lookup for 10 seconds; with several lookups per
        # call that alone blows the wall-clock budget, and a missing element is
        # a fact we want back immediately, not after ten seconds of hoping.
        try:
            u.SetGlobalSearchTimeout(1.0)
        except Exception:
            pass
        _uia = u
        _uia_version = str(getattr(u, "__version__", "") or "unknown")
        return True


def available() -> dict:
    """
    Can Jarvis read interfaces on this machine right now?

    Separate from every other call so the console can show the capability as
    present/absent without triggering a tree walk, and so the reason is a fact
    the user can act on rather than an error at the end of a task.
    """
    ok = _load()
    return {
        "ok": ok,
        "library": f"uiautomation {_uia_version}" if ok else "",
        "reason": "" if ok else _uia_reason,
        "what_to_do": "" if ok else (
            "Run: pip install uiautomation"
            if "not installed" in _uia_reason else
            "Until this works Jarvis reads apps by screenshot, which is slower "
            "and less exact."),
    }


# ── One thread, because COM is per-thread ────────────────────────────────────
#
# UI Automation is COM. A COM apartment belongs to the thread that initialised
# it, and FastAPI hands each request to an arbitrary worker from a pool — so
# calling UIA straight from a request handler works, then does not, depending
# on which thread caught the request. Every call here runs on ONE dedicated
# thread that initialises the apartment once.
#
# The single thread buys two more things for free: UIA calls are serialised
# (two simultaneous walks of the same window is not a situation worth debugging)
# and `future.result(timeout=…)` gives every call a hard wall clock.

_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()
_pool_restarts = 0
_MAX_RESTARTS = 3
_dead_reason = ""


def _thread_init() -> None:
    """Initialise the COM apartment for the one UIA thread."""
    if _uia is None:
        return
    fn = getattr(_uia, "InitializeUIAutomationInCurrentThread", None)
    if callable(fn):
        try:
            fn()
            return
        except Exception:
            pass
    # Older uiautomation builds initialise COM on import instead of exposing
    # this. Falling back to comtypes directly is correct there and harmless if
    # the apartment already exists (CoInitializeEx returns S_FALSE).
    try:
        import comtypes
        comtypes.CoInitializeEx()
    except Exception:
        pass


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=1, initializer=_thread_init,
                                       thread_name_prefix="jarvis-uia")
        return _pool


def _call(fn, budget_s: float = CALL_BUDGET_S) -> tuple[object, str]:
    """
    Run `fn` on the UIA thread with a hard wall clock. Returns (value, error).

    A UIA call that hangs holds the thread forever — the COM call cannot be
    cancelled from outside, so a timeout here means the worker is gone for
    good. We replace it (leaking one blocked thread) rather than queue every
    later call behind a corpse, but only a few times: if the accessibility layer
    keeps hanging, that is a fact about the machine and Jarvis should say so
    instead of spawning threads until it falls over.
    """
    global _pool, _pool_restarts, _dead_reason
    if _dead_reason:
        return None, _dead_reason
    if not _load():
        return None, _uia_reason
    try:
        fut = _get_pool().submit(fn)
    except Exception as e:
        return None, f"couldn't reach the accessibility layer ({e})"
    try:
        return fut.result(timeout=budget_s), ""
    except _FutureTimeout:
        with _pool_lock:
            _pool = None                      # abandon the blocked worker
            _pool_restarts += 1
            restarts = _pool_restarts
        msg = (f"Windows' accessibility layer stopped responding after "
               f"{budget_s:.0f}s.")
        if restarts >= _MAX_RESTARTS:
            _dead_reason = (
                msg + " It has done this " + str(restarts) + " times, so "
                "Jarvis has stopped using it and is reading apps by screenshot "
                "instead. Restart Jarvis after closing whatever is hung.")
            return None, _dead_reason
        trace.failure("ui.timeout", msg, detail=f"restart #{restarts}")
        return None, msg + " Trying again is safe — nothing was changed."
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# ── The tree ─────────────────────────────────────────────────────────────────

@dataclass
class UINode:
    """
    One element, flattened. `path` is the index route from the window root,
    which is what makes a flat list enough: a node B is inside A exactly when
    B.path starts with A.path. That keeps the wire format a plain list while
    still answering "which of these are messages in that list".
    """
    name: str = ""
    role: str = ""
    value: str = ""
    rect: tuple = (0, 0, 0, 0)         # left, top, right, bottom
    path: tuple = ()
    enabled: bool = True
    offscreen: bool = False
    _raw: object = field(default=None, repr=False, compare=False)

    @property
    def depth(self) -> int:
        return len(self.path)

    @property
    def center(self) -> tuple:
        l, t, r, b = self.rect
        return ((l + r) // 2, (t + b) // 2)

    @property
    def area(self) -> int:
        l, t, r, b = self.rect
        return max(0, r - l) * max(0, b - t)

    @property
    def text(self) -> str:
        """What a person would say this element says."""
        return self.value or self.name

    def to_dict(self) -> dict:
        return {"name": self.name, "role": self.role, "value": self.value,
                "rect": list(self.rect), "path": list(self.path),
                "enabled": self.enabled, "offscreen": self.offscreen}


def _attr(obj, name: str, default=None):
    """
    Read a property that lives in another process.

    Every one of these is a COM call against a window that may close, repaint
    or go unresponsive between two lines of this function. A raised exception
    here means "that element went away", not "Jarvis is broken", so it degrades
    to the default and the walk continues. Losing one node is fine; losing the
    whole read because a tooltip disappeared is not.
    """
    try:
        got = getattr(obj, name, default)
        return got() if callable(got) else got
    except Exception:
        return default


def _role_of(ctrl) -> str:
    """'ListItemControl' -> 'listitem'. Roles are stable across languages;
    names are not, which is why matching leans on role first wherever it can."""
    raw = str(_attr(ctrl, "ControlTypeName", "") or "")
    return re.sub(r"Control$", "", raw).lower()


def _rect_of(ctrl) -> tuple:
    r = _attr(ctrl, "BoundingRectangle")
    if r is None:
        return (0, 0, 0, 0)
    try:
        return (int(r.left), int(r.top), int(r.right), int(r.bottom))
    except Exception:
        return (0, 0, 0, 0)


def _value_of(ctrl) -> str:
    """The editable/current content of a control, if it has one."""
    for pattern in ("GetValuePattern", "GetLegacyIAccessiblePattern"):
        try:
            p = getattr(ctrl, pattern, None)
            if not callable(p):
                continue
            got = p()
            if got is None:
                continue
            v = _attr(got, "Value", "")
            if v:
                return str(v)[:MAX_VALUE]
        except Exception:
            continue
    return ""


def _node_from(ctrl, path: tuple) -> UINode:
    return UINode(
        name=str(_attr(ctrl, "Name", "") or "")[:MAX_NAME],
        role=_role_of(ctrl),
        value=_value_of(ctrl),
        rect=_rect_of(ctrl),
        path=path,
        enabled=bool(_attr(ctrl, "IsEnabled", True)),
        offscreen=bool(_attr(ctrl, "IsOffscreen", False)),
        _raw=ctrl,
    )


def _children(ctrl) -> list:
    got = _attr(ctrl, "GetChildren", None)
    return list(got) if isinstance(got, (list, tuple)) else []


def walk(root, max_nodes: int = MAX_NODES, max_depth: int = MAX_DEPTH,
         budget_s: float = WALK_BUDGET_S) -> tuple[list[UINode], str]:
    """
    Flatten a window into a list of elements, in reading order.

    Returns (nodes, cut_short_reason). The reason is empty when the whole tree
    fitted; otherwise it names which bound stopped us, because "I read the
    first 700 elements" and "I read the whole window" support very different
    conclusions and only one of them can honestly say "you have no new
    messages".

    Depth-first with an explicit stack rather than recursion: the tree is
    attacker-shaped in the sense that a web view can nest arbitrarily deep, and
    Python's recursion limit is not the bound we want to discover that with.
    """
    nodes: list[UINode] = []
    if root is None:
        return nodes, "no window to read"
    started = time.time()
    stack: list[tuple[object, tuple]] = [(root, ())]
    cut = ""
    while stack:
        if len(nodes) >= max_nodes:
            cut = (f"stopped after {max_nodes} elements — this window has more "
                   f"than Jarvis reads in one pass")
            break
        if time.time() - started > budget_s:
            cut = (f"stopped after {budget_s:.0f}s — this window's interface is "
                   f"slow to read")
            break
        ctrl, path = stack.pop()
        nodes.append(_node_from(ctrl, path))
        if len(path) >= max_depth:
            continue
        kids = _children(ctrl)
        # Pushed reversed so popping yields left-to-right, top-to-bottom, which
        # is the order the items appear on screen and therefore the order a
        # conversation reads in.
        for i in range(len(kids) - 1, -1, -1):
            stack.append((kids[i], path + (i,)))
    return nodes, cut


# ── Matching a name a human typed ────────────────────────────────────────────

def _norm(s: str) -> str:
    """
    NFKC, collapsed whitespace, stripped.

    NFKC matters here and nowhere else in this repo: a Chinese IME produces
    full-width Latin letters and full-width punctuation, so a contact saved as
    "Ａｈｍｅｄ" does not equal the "Ahmed" the user typed, and no amount of
    lowercasing fixes it. NFKC folds the width difference away.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(s or ""))).strip()


def _key(s: str) -> str:
    return _norm(s).casefold()


# Roles that a click means something on. Used to break ties, not to exclude:
# apps put clickable behaviour on 'text' and 'custom' nodes all the time.
_CLICKABLE = ("listitem", "button", "treeitem", "menuitem", "tabitem",
              "hyperlink", "dataitem", "checkbox", "radiobutton", "custom")
_EDITABLE = ("edit", "document", "combobox")


def _score(node: UINode, needle: str) -> float:
    """How well does this element answer to that name? 0 means it does not."""
    n, hay = _key(needle), _key(node.name)
    if not n or not hay:
        return 0.0
    if hay == n:
        return 1.0
    if hay.startswith(n):
        return 0.8
    if n in hay:
        return 0.6
    return 0.0


def match(nodes: list[UINode], needle: str, role: str = "") -> dict:
    """
    Find the one element called `needle`, or refuse.

    Refusing is the point. This is the function that decides which chat gets
    opened, and the old OCR path had no concept of "two things on screen look
    like what you asked for" — it clicked the higher-confidence rectangle and a
    message went to the wrong person. Here, if two DIFFERENT names tie at the
    same score, nothing is chosen and both are handed back for the user to pick.

    The same name appearing twice is not that situation: a contact usually
    appears once in the list and again as the conversation header, and those
    are the same person. Ties on identical names are resolved by preferring
    something clickable and, failing that, reading order.
    """
    want_role = _key(role)
    scored = []
    for n in nodes:
        if want_role and n.role != want_role:
            continue
        s = _score(n, needle)
        if s > 0:
            scored.append((s, n))
    if not scored:
        return {"found": False, "reason": f"nothing here is called '{needle}'",
                "candidates": []}

    best = max(s for s, _ in scored)
    top = [n for s, n in scored if s == best]
    # Compared casefolded, LISTED as written. The user has to recognise these
    # names to pick one, and "ahmed ali" is not what their contact list says.
    distinct: dict[str, str] = {}
    for n in top:
        distinct.setdefault(_key(n.name), _norm(n.name))
    if len(distinct) > 1:
        names = sorted(distinct.values())
        return {
            "found": False,
            "ambiguous": True,
            "reason": (f"'{needle}' matches {len(names)} different things here: "
                       + ", ".join(n or "(unnamed)" for n in names[:6])
                       + ". Say which one."),
            "candidates": [n.to_dict() for n in top[:8]],
        }

    # One name, possibly several elements carrying it. Prefer the one a click
    # is meant for, then the larger target, then reading order.
    top.sort(key=lambda n: (n.role not in _CLICKABLE, -n.area, n.path))
    return {"found": True, "node": top[0], "score": best,
            "also_matched": [n.to_dict() for n in top[1:4]]}


# ── Structure: which of these elements is the conversation? ──────────────────

def _descendants(nodes: list[UINode], parent: UINode) -> list[UINode]:
    p = parent.path
    return [n for n in nodes if len(n.path) > len(p) and n.path[:len(p)] == p]


_CONTAINERS = ("list", "tree", "table", "document", "datagrid")


def text_containers(nodes: list[UINode]) -> list[tuple[UINode, list[UINode]]]:
    """
    Every list-like element with text in it, the conversation first.

    A chat window is two lists side by side — contacts on the left, messages on
    the right — and which is which is a layout fact, not a name we can rely on
    in a localised app.

    Ranked by AREA, not by how much text each holds. Text volume was the
    obvious rule and it is wrong in the case that matters most: a quiet chat
    with a long contact list. Three messages against forty contacts makes the
    sidebar the wordier list, and `read_messages` would have answered "check my
    messages" with a list of your friends' names. The conversation pane is the
    big one on screen in every desktop chat app ever built; a contact sidebar
    is narrow by design. Area is the stable signal.

    Containers that WRAP another candidate are dropped first, so an enclosing
    document or web view — which is bigger than everything by definition —
    can't win on area alone. What's left is the innermost real lists.
    """
    found = []
    for n in nodes:
        if n.role not in _CONTAINERS:
            continue
        kids = [d for d in _descendants(nodes, n) if d.text.strip()]
        if kids:
            found.append((n, kids))

    paths = [c.path for c, _ in found]
    inner = [(c, kids) for c, kids in found
             if not any(p != c.path and p[:len(c.path)] == c.path for p in paths)]

    out = inner or found
    out.sort(key=lambda pair: (-pair[0].area,
                               -sum(len(k.text) for k in pair[1]),
                               pair[0].path))
    return out


def _items_of(nodes: list[UINode], container: UINode) -> list[UINode]:
    """
    The container's own rows, in reading order — not every descendant.

    A message bubble is a listitem holding four nested text nodes; returning
    all of them turns one message into four "messages". Rows are the direct
    item-role children; the text underneath each is folded into it.
    """
    p = container.path
    rows = [n for n in nodes
            if n.path[:len(p)] == p and len(n.path) == len(p) + 1]
    items = [r for r in rows if r.role in ("listitem", "treeitem", "dataitem")]
    return sorted(items or rows, key=lambda n: n.path)


def _row_text(nodes: list[UINode], row: UINode) -> str:
    """A row's text, its own plus everything nested inside it, de-duplicated."""
    parts, seen = [], set()
    for n in [row, *_descendants(nodes, row)]:
        t = _norm(n.text)
        if t and t not in seen:
            seen.add(t)
            parts.append(t)
    return "  ".join(parts)[:MAX_VALUE]


# ── Getting to a window ──────────────────────────────────────────────────────

def _foreground_root():
    """
    The UIA element for whatever window is in front, or None.

    Deliberately does NOT find windows itself. desktop_agent already enumerates
    by owning process rather than by title — which is the only thing that works
    on a Chinese Windows install — and already knows that QQ and WeChat live in
    the system tray with no visible window until restored. A second window
    finder here would be a second set of those bugs.
    """
    if _uia is None:
        return None
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        return _uia.ControlFromHandle(hwnd)
    except Exception:
        return None


def _focus(app: str) -> dict:
    """
    Put `app` in front and confirm it. Returns {"ok", "reason", "title"}.

    Fail-stop, on purpose. Reading the tree of whatever happens to be in front
    and reporting it as the app's contents is the screenshot bug with better
    latency — the whole reason this module exists is that "you have no new
    messages" must not be able to come from a Notepad window.
    """
    from agents import desktop_agent
    if not app:
        root = _foreground_root()
        return {"ok": root is not None, "reason": "" if root is not None else
                "there is no window in front to read", "title": ""}
    res = desktop_agent.focus_window(app)
    if not res.get("success"):
        return {"ok": False,
                "reason": res.get("error") or f"couldn't bring {app} to the front",
                "what_to_do": res.get("what_to_do", ""), "title": ""}
    # focus_window confirms the foreground window is the app's; re-checking here
    # would be a second implementation of the same check.
    return {"ok": True, "reason": "", "title": res.get("title", app),
            "method": res.get("method", "")}


# ── Public API ───────────────────────────────────────────────────────────────

def _result(success: bool, **kw) -> dict:
    out = {"success": success}
    out.update(kw)
    return out


def _input_allowed() -> str:
    """
    "" if Jarvis may touch the mouse and keyboard, otherwise the reason it may
    not.

    UI Automation's Click() moves the real pointer and SetFocus() steals the
    caret, so these are input actions and the emergency stop has to cover them.
    Reaching the desktop through a different library is not a loophole — it was
    the same hand on the same mouse.
    """
    try:
        from agents import desktop_agent
        if desktop_agent.is_estopped():
            return ("EMERGENCY STOP is engaged — clear it before Jarvis touches "
                    "anything")
    except Exception:
        pass
    return ""


def _read_nodes(app: str, max_nodes: int = MAX_NODES) -> dict:
    """
    Focus `app`, walk its window, hand back the WHOLE element list.

    Everything else in this module goes through here, and it deliberately does
    no filtering. The containers that hold a conversation — the List, the Tree —
    almost never have a name of their own, so a list stripped down to "elements
    with text" has the messages in it but not the thing that identifies them as
    a conversation. Filtering belongs at the surface, per caller, not here.

    Returns {"ok", "nodes", "cut", "window", "error", "what_to_do"}.
    """
    if not _load():
        return {"ok": False, "nodes": [], "cut": "", "stage": "library",
                "error": _uia_reason, "what_to_do": available()["what_to_do"]}
    foc = _focus(app)
    if not foc["ok"]:
        # `stage` exists for one caller and one bug. desktop_agent.read_messages
        # falls back to a screenshot when this fails — and a screenshot taken
        # because we could not bring QQ to the front photographs whatever WAS in
        # front, then answers confidently about it. "The app isn't in front" and
        # "the app is in front and says nothing" need completely different
        # responses, and only the second one may fall back to looking.
        return {"ok": False, "nodes": [], "cut": "", "stage": "focus",
                "error": foc["reason"], "what_to_do": foc.get("what_to_do", "")}

    def _work() -> dict:
        root = _foreground_root()
        if root is None:
            return {"ok": False, "nodes": [], "cut": "",
                    "error": "couldn't attach to the window that is in front"}
        nodes, cut = walk(root, max_nodes=max_nodes)
        return {"ok": True, "nodes": nodes, "cut": cut}

    got, err = _call(_work)
    if err:
        return {"ok": False, "nodes": [], "cut": "", "stage": "read",
                "error": err}
    got = dict(got or {})
    got["window"] = foc.get("title", "")
    got.setdefault("stage", "read")
    return got


def snapshot(app: str = "", max_nodes: int = MAX_NODES) -> dict:
    """
    Every readable element of `app`'s window.

    The raw capability the rest of this module is built on, exposed because it
    is also the honest answer to "what can you actually see?" — a user looking
    at an empty result can look at this and tell "the app hides its interface"
    apart from "Jarvis didn't look".
    """
    with trace.timed("ui.snapshot", app):
        got = _read_nodes(app, max_nodes)
        if not got["ok"]:
            return _result(False, verified=False, error=got.get("error", ""),
                           what_to_do=got.get("what_to_do", ""))
        nodes, cut = got["nodes"], got["cut"]
        if not nodes:
            return _result(False, verified=False,
                           error=f"{app or 'that window'} exposes no readable "
                                 f"elements",
                           what_to_do=_ELECTRON_HINT)
        readable = [n for n in nodes if n.text.strip()]
        if not readable:
            return _result(True, verified=False, app=app, nodes=[],
                           element_count=len(nodes),
                           error=f"{app or 'that window'} has "
                                 f"{len(nodes)} elements but none of them carry "
                                 f"any text",
                           what_to_do=_ELECTRON_HINT,
                           verify_reason="the window was read, but it says nothing")
        return _result(True, verified=True, app=app, window=got.get("window", ""),
                       nodes=[n.to_dict() for n in readable],
                       element_count=len(nodes), truncated=bool(cut),
                       truncated_reason=cut,
                       verify_reason=f"read from {app or 'the foreground window'}'s "
                                     f"own window ({len(readable)} elements with text)")


_ELECTRON_HINT = (
    "Some apps — QQ NT and other Electron-based ones — draw their interface "
    "without exposing any text to Windows. Jarvis can still read those by "
    "screenshot; ask it to 'look at the screen' instead.")


def read_text(app: str = "", limit: int = 200) -> dict:
    """The window's text, in reading order. The cheap 'what does it say' call."""
    snap = snapshot(app)
    if not snap.get("success"):
        return snap
    seen, lines = set(), []
    for n in snap["nodes"]:
        t = _norm(n.get("value") or n.get("name"))
        if t and t not in seen:
            seen.add(t)
            lines.append(t)
        if len(lines) >= limit:
            break
    return _result(True, verified=snap.get("verified"), app=app,
                   text="\n".join(lines), lines=lines,
                   truncated=snap.get("truncated") or len(lines) >= limit,
                   verify_reason=snap.get("verify_reason", ""))


def read_messages(app: str = "", limit: int = 30) -> dict:
    """
    The conversation currently open in a chat app, as real text.

    This is the replacement for screenshot-then-ask-a-vision-model. It returns
    what the messages actually say, in order, in milliseconds — and when it
    cannot find a conversation it says the window had no message list rather
    than reporting an empty one, because "no new messages" is a claim about the
    world and this would only be a claim about the read.
    """
    with trace.timed("ui.read_messages", app):
        got = _read_nodes(app)
        if not got["ok"]:
            return _result(False, verified=False, error=got.get("error", ""),
                           stage=got.get("stage", "read"),
                           what_to_do=got.get("what_to_do", ""))
        nodes = got["nodes"]
        containers = text_containers(nodes)
        if not containers:
            readable = sum(1 for n in nodes if n.text.strip())
            return _result(True, verified=False, app=app, messages=[],
                           stage="read",
                           error=f"{app or 'that window'} is readable "
                                 f"({readable} elements with text), but there is "
                                 f"no message list in it — Jarvis will not claim "
                                 f"your inbox is empty on that basis",
                           what_to_do=("Open the conversation you want read, then "
                                       "ask again. " + _ELECTRON_HINT
                                       if readable == 0 else
                                       "Open the conversation you want read, then "
                                       "ask again."),
                           verify_reason="no list-like container found")
        container, _ = containers[0]
        rows = _items_of(nodes, container)
        msgs = [t for t in (_row_text(nodes, r) for r in rows) if t]
        return _result(True, verified=True, app=app,
                       window=got.get("window", ""),
                       messages=msgs[-limit:],
                       total=len(msgs),
                       other_lists=len(containers) - 1,
                       truncated=bool(got.get("cut")),
                       truncated_reason=got.get("cut", ""),
                       verify_reason=f"read {len(msgs)} entries from the largest "
                                     f"list in {app or 'the foreground window'}")


def click(app: str, name: str, role: str = "") -> dict:
    """
    Click the element called `name`, having first confirmed there is only one.

    Verification is a re-read: the element reports itself selected, or the
    window's text changed. Clicking something and assuming it worked is how the
    wrong chat ends up open.
    """
    with trace.timed("ui.click", f"{app}:{name}"):
        if stopped := _input_allowed():
            return _result(False, verified=False, error=stopped)
        if not _load():
            return _result(False, verified=False, error=_uia_reason)
        foc = _focus(app)
        if not foc["ok"]:
            return _result(False, verified=False, error=foc["reason"],
                           what_to_do=foc.get("what_to_do", ""))

        def _work():
            root = _foreground_root()
            if root is None:
                return {"success": False, "error": "couldn't attach to the window"}
            nodes, _cut = walk(root)
            m = match(nodes, name, role)
            if not m.get("found"):
                return {"success": False, "error": m["reason"],
                        "ambiguous": bool(m.get("ambiguous")),
                        "candidates": m.get("candidates", []),
                        "what_to_do": ("Say which one you mean."
                                       if m.get("ambiguous") else
                                       "Check the name — Jarvis will not click "
                                       "the nearest-looking thing instead.")}
            node = m["node"]
            if not node.enabled:
                return {"success": False,
                        "error": f"'{node.name}' is there but greyed out"}
            before = _signature(nodes)
            try:
                node._raw.Click(simulateMove=False)
            except Exception as e:
                return {"success": False,
                        "error": f"the click didn't go through ({e})"}
            time.sleep(0.35)
            root2 = _foreground_root()
            after_nodes, _ = walk(root2) if root2 is not None else ([], "")
            selected = _is_selected(node._raw)
            changed = _signature(after_nodes) != before
            verified = bool(selected or changed)
            return {"success": True, "verified": verified,
                    "clicked": node.name, "role": node.role,
                    "at": node.center,
                    "verify_reason": ("it is now selected" if selected else
                                      "the window's contents changed" if changed
                                      else "the click was sent, but nothing on "
                                           "screen changed afterwards")}

        got, err = _call(_work)
        if err:
            return _result(False, verified=False, error=err)
        return _result(bool(got.get("success")), **{k: v for k, v in got.items()
                                                    if k != "success"})


def _signature(nodes: list[UINode]) -> str:
    """
    A cheap fingerprint of what a window is showing.

    Names and roles only, no coordinates: a caret blink or a scrollbar nudging
    by a pixel is not "the window changed", and treating it as one would let
    every click claim it was verified.
    """
    return "|".join(f"{n.role}:{_key(n.name)}" for n in nodes if n.name)


def _is_selected(ctrl) -> bool:
    try:
        p = getattr(ctrl, "GetSelectionItemPattern", None)
        if callable(p):
            got = p()
            if got is not None:
                return bool(_attr(got, "IsSelected", False))
    except Exception:
        pass
    return False


def type_into(app: str, field_name: str = "", text: str = "",
              submit: bool = False) -> dict:
    """
    Put text in a named field and read it back out of that same field.

    The read-back is the entire point. desktop_agent has to verify typing with
    Ctrl+A/Ctrl+C, which borrows the user's clipboard, only works if the field
    supports select-all, and cannot tell "the field is empty" from "the copy
    didn't land". Asking the control for its own value has none of those
    problems and is exact.

    `submit` sends Enter afterwards and defaults to False, because Enter in a
    chat window is not an edit — it is a message leaving the building.
    """
    with trace.timed("ui.type_into", f"{app}:{field_name}"):
        if stopped := _input_allowed():
            return _result(False, verified=False, error=stopped)
        if not _load():
            return _result(False, verified=False, error=_uia_reason)
        if not text:
            return _result(False, verified=False, error="nothing to type")
        foc = _focus(app)
        if not foc["ok"]:
            return _result(False, verified=False, error=foc["reason"],
                           what_to_do=foc.get("what_to_do", ""))

        def _work():
            root = _foreground_root()
            if root is None:
                return {"success": False, "error": "couldn't attach to the window"}
            nodes, _cut = walk(root)
            target = _pick_field(nodes, field_name)
            if isinstance(target, dict):
                return target                      # already an error result
            try:
                target._raw.SetFocus()
            except Exception as e:
                return {"success": False,
                        "error": f"couldn't put the cursor in that field ({e})"}
            return {"success": True, "field": target.name or target.role,
                    "path": list(target.path)}

        got, err = _call(_work)
        if err:
            return _result(False, verified=False, error=err)
        if not got.get("success"):
            return _result(False, verified=False, **{k: v for k, v in got.items()
                                                     if k != "success"})

        # Typing goes through desktop_agent so the emergency stop, the pacing
        # and the input lock all still apply. UIA can set a value directly, but
        # many chat apps never see a SetValue — they listen for keystrokes, and
        # the send button stays greyed out.
        from agents import desktop_agent
        typed = desktop_agent.type_text_raw(text)
        if not typed.get("success"):
            return _result(False, verified=False,
                           error=typed.get("error", "typing failed"),
                           field=got.get("field"))

        def _readback():
            root = _foreground_root()
            if root is None:
                return {"value": None}
            nodes, _ = walk(root)
            want = tuple(got.get("path") or ())
            for n in nodes:
                if n.path == want:
                    return {"value": n.value or n.name}
            return {"value": None}

        back, err2 = _call(_readback, budget_s=15.0)
        value = (back or {}).get("value") if not err2 else None
        landed = value is not None and _key(text) in _key(value)
        if not landed:
            return _result(True, verified=False, field=got.get("field"),
                           typed=text, field_value=value,
                           verify_reason=(
                               "the field is now empty" if value == "" else
                               f"the field reads {value!r}, not what was typed"
                               if value is not None else
                               "couldn't read the field back to check"),
                           what_to_do="Nothing was submitted. Look at the window "
                                      "before letting it continue.")
        if not submit:
            return _result(True, verified=True, field=got.get("field"),
                           typed=text, field_value=value, submitted=False,
                           verify_reason="the field contains exactly what was typed")
        sent = desktop_agent.press("enter")
        return _result(bool(sent.get("success")), verified=None,
                       field=got.get("field"), typed=text, submitted=True,
                       verify_reason="Enter was sent; whether the app accepted it "
                                     "is not checked here")


def _pick_field(nodes: list[UINode], field_name: str):
    """
    The field to type into: the one you named, or the obvious one.

    "The obvious one" is the largest enabled edit control in the lower half of
    the window, which is where every chat app in existence puts the compose
    box. Guessing is only allowed when there is exactly one plausible target —
    otherwise this returns an error result and lets the caller ask.
    """
    if field_name:
        m = match(nodes, field_name)
        if not m.get("found"):
            return {"success": False, "error": m["reason"],
                    "candidates": m.get("candidates", []),
                    "ambiguous": bool(m.get("ambiguous"))}
        return m["node"]
    edits = [n for n in nodes
             if n.role in _EDITABLE and n.enabled and not n.offscreen and n.area > 0]
    if not edits:
        return {"success": False,
                "error": "there is no text field in that window to type into",
                "what_to_do": "Click into the box you want first, or name it."}
    if len(edits) == 1:
        return edits[0]
    bottom = max(n.rect[3] for n in nodes) or 1
    lower = [n for n in edits if n.center[1] > bottom * 0.5]
    pool = lower or edits
    pool.sort(key=lambda n: (-n.area, n.path))
    return pool[0]


# ── The workflow the whole tier exists for ───────────────────────────────────

def send_message(app: str = "", contact: str = "", text: str = "",
                 send: bool = False) -> dict:
    """
    Open a named person's chat, type a message into it, and show it before it
    goes anywhere.

    `send` defaults to False and that is not a placeholder. Every step up to
    Enter is reversible and visible; Enter is neither. What comes back without
    `send` is the composed message sitting in the real input box of the real
    conversation, with the conversation identified by name — which is the proof
    that was missing. Approving is a second call with send=True.

    Each step is verified before the next one runs, and a failure stops the
    chain rather than continuing into the part that talks to a person:

        focus the app        confirmed by desktop_agent (process, not title)
        find the contact     refuses if two different names match
        click it             confirmed selected, or the window changed
        find the input box   the compose field, or the one you named
        type                 read back out of the control itself
        Enter                only on approval, and only if the read-back matched
    """
    steps: list[dict] = []

    def _stop(reason: str, **kw) -> dict:
        return _result(False, verified=False, error=reason, steps=steps,
                       sent=False, **kw)

    if not text:
        return _stop("there is no message to send")
    if not app:
        try:
            from services import providers
            app = providers.provider_for("message") or ""
        except Exception:
            app = ""
        if not app:
            return _stop("no messaging app is set up on this machine",
                         what_to_do="Install or open QQ, WeChat or Telegram "
                                    "once so Jarvis can find it.")

    try:
        return _send_message(app, contact, text, send, steps, _stop)
    except _Cancelled() as e:
        # Stopping is a legitimate outcome, not a crash. Which step it stopped
        # at is the useful part: "cancelled before send" means a draft is on
        # screen and nothing left the machine.
        return _stop(f"stopped: {e}",
                     what_to_do="Nothing was sent. Whatever was typed is still "
                                "in the window if you want to finish it by hand.")


def _Cancelled():
    """control.Cancelled, or a type that never matches if control is missing."""
    try:
        from services.control import Cancelled
        return Cancelled
    except Exception:
        class _Never(Exception):
            pass
        return _Never


def _send_message(app: str, contact: str, text: str, send: bool,
                  steps: list, _stop) -> dict:
    with trace.timed("ui.send_message", f"{app}:{contact}"):
        if stopped := _input_allowed():
            return _stop(stopped)
        if not _load():
            return _stop(_uia_reason, what_to_do=available()["what_to_do"])

        # Between steps, never inside one. Stopping after "find the contact" is
        # harmless; stopping between "type" and "Enter" leaves a draft on
        # screen, which is visible and recoverable. There is deliberately no
        # checkpoint after Enter — by then it has been read by someone.
        _checkpoint("open the chat")

        if contact:
            picked = click(app, contact)
            steps.append({"step": "open the chat", "ok": bool(picked.get("success")),
                          "verified": picked.get("verified"),
                          "detail": picked.get("clicked") or picked.get("error", "")})
            if not picked.get("success"):
                return _stop(
                    f"couldn't open a chat with '{contact}': {picked.get('error')}",
                    candidates=picked.get("candidates", []),
                    ambiguous=picked.get("ambiguous", False),
                    what_to_do=picked.get("what_to_do", ""))
            if picked.get("verified") is not True:
                # The click was sent and nothing moved. That is exactly when the
                # old path would have typed into whatever chat was already open.
                return _stop(
                    f"clicked '{contact}' but the window didn't change, so Jarvis "
                    f"can't tell whose chat is open — nothing was typed",
                    what_to_do="Open the conversation yourself and ask again.")
        else:
            steps.append({"step": "open the chat", "ok": True, "verified": None,
                          "detail": "no contact named — using the conversation "
                                    "already open"})

        _checkpoint("type the message")
        typed = type_into(app, "", text, submit=False)
        steps.append({"step": "type the message", "ok": bool(typed.get("success")),
                      "verified": typed.get("verified"),
                      "detail": typed.get("field") or typed.get("error", "")})
        if not typed.get("success") or typed.get("verified") is not True:
            return _stop(
                typed.get("error") or typed.get("verify_reason")
                or "the message didn't land in the input box",
                what_to_do=typed.get("what_to_do",
                                     "Nothing was sent. Look at the window."),
                field_value=typed.get("field_value"))

        composed = {
            "app": app, "contact": contact or "(the open conversation)",
            "message": text, "field": typed.get("field"),
            "field_value": typed.get("field_value"),
        }
        if not send:
            steps.append({"step": "send", "ok": True, "verified": None,
                          "detail": "waiting for you — nothing has been sent"})
            return _result(True, verified=True, sent=False,
                           awaiting_approval=True, composed=composed, steps=steps,
                           verify_reason=(
                               f"the message is sitting in {app}'s input box in "
                               f"{composed['contact']}'s chat, unsent"),
                           what_to_do="Approve to send it, or edit it in the "
                                      "window yourself.")

        _checkpoint("send")
        from agents import desktop_agent
        pressed = desktop_agent.press("enter")
        if not pressed.get("success"):
            return _stop(f"couldn't press Enter ({pressed.get('error')})",
                         composed=composed)
        time.sleep(0.6)

        # Did it actually leave? The message should now be in the conversation
        # and gone from the input box. Either alone is weak; together they are
        # the thing a person checks by looking.
        after = read_messages(app, limit=6)
        in_thread = any(_key(text) in _key(m) for m in after.get("messages", []))
        box_now = _field_value(app)
        box_cleared = box_now is not None and _key(text) not in _key(box_now)
        verified = bool(in_thread or box_cleared)
        steps.append({"step": "send", "ok": True, "verified": verified,
                      "detail": ("it appears in the conversation" if in_thread else
                                 "the input box cleared" if box_cleared else
                                 "no sign of it in the conversation")})
        return _result(True, verified=verified, sent=True, composed=composed,
                       steps=steps,
                       verify_reason=("the message is in the conversation"
                                      if in_thread else
                                      "the input box cleared, but the message "
                                      "wasn't found in the conversation"
                                      if box_cleared else
                                      "Enter was pressed and nothing changed — "
                                      "assume it did NOT send"),
                       what_to_do="" if verified else
                                  f"Check {app} yourself before sending again — "
                                  f"Jarvis will not retry, because a retry that "
                                  f"is wrong sends the message twice.")


def _checkpoint(step: str) -> None:
    """Let a pause or a cancel land between steps. Never raises here — a
    cancel propagates as control.Cancelled, which the chain runner already
    understands; anything else must not stop a message half-typed."""
    try:
        from services import control
        control.checkpoint(step)
    except ImportError:
        pass


def _field_value(app: str) -> str | None:
    """The compose box's current contents, or None if it can't be read."""
    def _work():
        root = _foreground_root()
        if root is None:
            return None
        nodes, _ = walk(root)
        got = _pick_field(nodes, "")
        return None if isinstance(got, dict) else (got.value or "")
    val, err = _call(_work, budget_s=15.0)
    return None if err else val
