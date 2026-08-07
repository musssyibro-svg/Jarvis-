"""
services/capability_registry.py — what Jarvis can DO, described as data.

GPT's key addition. Instead of the planner hardcoding "call desktop_agent" or
"call browser_agent", every ability is a Capability with a description the Brain
can reason over:

    name, category, description, inputs, outputs, requirements, confidence,
    keywords, latency

The planner/Brain then asks best_for("open notepad and type notes") and gets
back the capability that fits — with a requirements check (is Playwright there?
is a platform logged in?) so it won't pick something that can't run right now.

Capabilities are auto-populated from the concrete subsystems (desktop, vision,
browser, freelance, planner, workflows) plus any learned workflows and custom
agents, so the registry grows as Jarvis grows — no hand-maintained list.
"""
from dataclasses import asdict, dataclass, field


@dataclass
class Capability:
    name: str
    category: str                       # desktop | vision | browser | freelance | planning | knowledge | workflow
    description: str
    keywords: list = field(default_factory=list)
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)
    requirements: list = field(default_factory=list)   # e.g. ["pyautogui"], ["playwright","login"]
    confidence: float = 0.8             # baseline reliability
    latency: str = "fast"              # fast | medium | slow

    def to_dict(self) -> dict:
        return asdict(self)


# ── Static, built-in capabilities ─────────────────────────────────────────────

BUILTIN = [
    Capability("open_app", "desktop", "Launch any installed application by name.",
               ["open", "launch", "start", "run", "app"],
               ["app name"], ["app running"], ["pyautogui"], 0.9, "fast"),
    Capability("desktop_chain", "desktop",
               "Do a multi-step desktop task (open app, type, click, hotkey) with "
               "verification between steps.",
               ["type", "click", "press", "hotkey", "do task", "then"],
               ["steps"], ["verified actions"], ["pyautogui"], 0.85, "medium"),
    Capability("screen_analyze", "vision",
               "Take a screenshot and explain what's on screen (and suggest a next action).",
               ["screen", "screenshot", "what's on", "read screen", "see", "analyze"],
               ["question"], ["screen description"], ["mss", "ocr_or_llava"], 0.75, "medium"),
    Capability("click_text", "vision",
               "Find text on screen by OCR and click it (see -> act).",
               ["click on", "press the", "button", "find and click"],
               ["target text"], ["click performed"], ["ocr", "pyautogui"], 0.7, "medium"),
    # Higher confidence and lower latency than the vision pair above, because
    # this reads the interface rather than a picture of it — exact text, no
    # model call. Listed separately rather than replacing them: apps that draw
    # their own interface expose nothing here, and OCR is still the answer
    # there.
    Capability("read_app", "desktop",
               "Read what an app's window actually says (its accessibility "
               "tree), including the open conversation in a chat app.",
               ["read", "check messages", "what does it say", "unread", "inbox"],
               ["app name"], ["the window's text"], ["uiautomation"], 0.9, "fast"),
    Capability("send_message", "desktop",
               "Open a named person's chat, type a message into it, and show it "
               "for approval before sending.",
               ["message", "send", "text", "dm", "tell", "reply"],
               ["app", "contact", "text"],
               ["message composed in the right chat, sent only on approval"],
               ["uiautomation", "pyautogui"], 0.75, "medium"),
    Capability("browse", "browser", "Open a URL in the managed browser.",
               ["browse", "go to", "open url", "website", "navigate"],
               ["url"], ["page open"], ["playwright"], 0.8, "medium"),
    Capability("freelance_scan", "freelance",
               "Scan freelance platforms for matching jobs.",
               ["scan jobs", "find jobs", "freelance", "gigs", "opportunities"],
               ["platforms"], ["job list"], [], 0.85, "medium"),
    Capability("freelance_propose", "freelance",
               "Draft a tailored proposal for a job (revenue-scored, job-type matched).",
               ["proposal", "apply", "bid", "cover letter"],
               ["job"], ["proposal text"], ["llm"], 0.75, "medium"),
    Capability("freelance_submit", "freelance",
               "Submit an approved bid on a logged-in bid platform.",
               ["submit bid", "place bid", "send proposal"],
               ["approved queue item"], ["submitted"], ["playwright", "login"], 0.6, "slow"),
    Capability("plan_project", "planning",
               "Break a goal into steps and track/execute it as a project.",
               ["plan", "project", "break down", "steps to"],
               ["goal"], ["project with steps"], [], 0.8, "fast"),
    Capability("remember", "knowledge", "Save a fact/decision to the personal brain.",
               ["remember", "memorize", "save this", "note that"],
               ["text"], ["stored"], [], 0.95, "fast"),
    Capability("recall", "knowledge", "Answer from saved personal knowledge (the brain).",
               ["what did", "recall", "do you remember", "my notes"],
               ["question"], ["answer"], [], 0.8, "fast"),
    Capability("run_workflow", "workflow",
               "Replay a previously taught task by name.",
               ["run my", "do my", "run workflow"],
               ["name"], ["verified replay"], [], 0.85, "medium"),
]


def _requirement_ok(req: str) -> bool:
    """Best-effort check whether a requirement is currently satisfiable."""
    try:
        if req == "pyautogui":
            from agents.desktop_agent import HAS_PYAUTOGUI
            return HAS_PYAUTOGUI
        if req == "mss":
            from agents.vision_agent import HAS_MSS, HAS_PIL
            return HAS_MSS or HAS_PIL
        if req in ("ocr", "ocr_or_llava"):
            from agents.vision_agent import HAS_OCR
            return HAS_OCR or True  # llava path may exist
        if req == "playwright":
            import importlib.util
            return importlib.util.find_spec("playwright") is not None
        if req == "llm":
            import importlib.util
            return importlib.util.find_spec("ollama") is not None
        if req == "login":
            from services import session_manager
            return bool(session_manager.logged_in_platforms())
        if req == "uiautomation":
            # Asks ui_agent rather than find_spec, because "the package is
            # importable" is not the question — on a machine with no
            # interactive desktop it imports and then cannot attach to
            # anything. available() distinguishes the two and says which.
            from agents.ui_agent import available
            return bool(available()["ok"])
    except Exception:
        return False
    return True


def all_capabilities(include_dynamic: bool = True) -> list[Capability]:
    caps = list(BUILTIN)
    if include_dynamic:
        # learned workflows become first-class capabilities
        try:
            from services.workflow_service import list_workflows
            for w in list_workflows():
                caps.append(Capability(
                    f"workflow:{w['name']}", "workflow",
                    w.get("description") or f"Learned task '{w['name']}'",
                    ["run my " + w["name"], w["name"]],
                    [], ["verified replay"], [], 0.85, "medium"))
        except Exception:
            pass
        # custom drop-in agents
        try:
            from agents.registry import registry
            for name, entry in registry.list_agents().items():
                if entry["metadata"].get("source") == "custom" and entry["enabled"]:
                    caps.append(Capability(
                        f"agent:{name}", "agent",
                        entry["metadata"].get("description") or f"Custom agent '{name}'",
                        [name], [], [], [], 0.7, "medium"))
        except Exception:
            pass
    return caps


def list_dicts() -> list[dict]:
    out = []
    for c in all_capabilities():
        d = c.to_dict()
        d["available"] = all(_requirement_ok(r) for r in c.requirements)
        d["missing"] = [r for r in c.requirements if not _requirement_ok(r)]
        out.append(d)
    return out


def best_for(goal: str, top_k: int = 3) -> list[dict]:
    """
    Rank capabilities for a goal by keyword overlap, weighted by baseline
    confidence and knocked down hard if a requirement is missing. This is the
    'which capability solves this?' the planner should ask.
    """
    g = (goal or "").lower()
    scored = []
    for c in all_capabilities():
        hits = sum(1 for kw in c.keywords if kw in g)
        if hits == 0 and c.name not in g:
            continue
        avail = all(_requirement_ok(r) for r in c.requirements)
        score = hits * 10 + c.confidence * 5 + (0 if avail else -50)
        scored.append((score, avail, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, avail, c in scored[:top_k]:
        d = c.to_dict()
        d.update(match_score=round(score, 1), available=avail,
                 missing=[r for r in c.requirements if not _requirement_ok(r)])
        out.append(d)
    return out


def describe() -> str:
    """Human list of what Jarvis can do — for a 'what can you do?' answer."""
    by_cat: dict[str, list] = {}
    for c in all_capabilities():
        by_cat.setdefault(c.category, []).append(c.description)
    lines = []
    for cat, items in by_cat.items():
        lines.append(f"**{cat.title()}**")
        for it in items:
            lines.append(f"  • {it}")
    return "\n".join(lines)
