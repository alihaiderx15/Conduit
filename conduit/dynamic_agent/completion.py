"""Deterministic completion checks for dynamic agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .context import AgentContext


@dataclass(frozen=True, slots=True)
class CompletionEvidence:
    complete: bool
    message: str = ""
    applicable: bool = False
    recommended_action: str | None = None
    recommended_arguments: dict[str, object] | None = None


class CompletionVerifier(Protocol):
    def verify(self, context: AgentContext) -> CompletionEvidence:
        ...


class StructuredFileGoalVerifier:
    """Verify common exact-path file goals from concrete action evidence.

    The verifier activates only when the run was given both ``target_path`` and
    ``expected_text`` initial variables. It never infers success from model text.
    """

    def verify(self, context: AgentContext) -> CompletionEvidence:
        target = context.store.get("target_path", None)
        expected = context.store.get("expected_text", None)
        if not target or expected is None:
            return CompletionEvidence(False, applicable=False)

        target_norm = str(target).casefold()
        wrote = False
        exists = False
        content_match = False
        opened = False

        for obs in context.observations:
            if not obs.success:
                continue
            path = str(obs.data.get("path", obs.arguments.get("path", "")))
            if path.casefold() != target_norm:
                continue
            if obs.action == "files.write_text":
                wrote = True
            elif obs.action == "files.exists" and obs.data.get("exists") is True:
                exists = True
            elif obs.action == "files.read_text":
                actual = obs.data.get("content", obs.data.get("text"))
                content_match = actual == expected
            elif obs.action == "system.open_path":
                opened = True

        goal_lower = context.goal.casefold()
        needs_open = "open" in goal_lower
        needs_exists = any(term in goal_lower for term in ("exist", "verify", "filesystem"))
        complete = wrote and content_match and (exists if needs_exists else True) and (opened if needs_open else True)
        if not complete:
            return CompletionEvidence(False, applicable=True)

        return CompletionEvidence(
            True,
            "Goal verified from filesystem evidence: the file was written, its exact contents were read back"
            + (", existence was confirmed" if needs_exists else "")
            + (", and it was opened successfully" if needs_open else "")
            + ".",
            applicable=True,
        )


class WindowsClipboardProcessVerifier:
    """Verify the General PC v1.1 Notepad/clipboard/window benchmark."""

    def verify(self, context: AgentContext) -> CompletionEvidence:
        expected = context.store.get("expected_text", None)
        if expected is None:
            return CompletionEvidence(False, applicable=False)
        goal = context.goal.casefold()
        if "clipboard" not in goal or "minimize" not in goal or "notepad" not in goal:
            return CompletionEvidence(False, applicable=False)

        clipboard_ok = False
        minimized = False
        process_ok = False
        typed = False

        for obs in context.observations:
            if not obs.success:
                continue
            if obs.action == "desktop.type":
                typed = True
            elif obs.action == "clipboard.read":
                clipboard_ok = str(obs.data.get("text", "")).strip() == str(expected)
            elif obs.action == "system.window_state":
                minimized = obs.data.get("state") == "minimize"
            elif obs.action == "system.list_processes":
                processes = [str(item).casefold() for item in obs.data.get("processes", [])]
                process_ok = any(name in {"notepad.exe", "notepad"} for name in processes)

        if typed and clipboard_ok and minimized and process_ok:
            return CompletionEvidence(
                True,
                "Goal verified from Windows evidence: the exact text was typed and copied, "
                "the clipboard matched, Notepad was minimized, and its process remained running.",
                applicable=True,
            )
        return CompletionEvidence(
            False,
            "Required Windows evidence is still missing. Verify the clipboard, minimized window state, "
            "and the running Notepad process before finishing.",
            applicable=True,
        )


class CompositeCompletionVerifier:
    """Return the first positive result from multiple deterministic verifiers."""

    def __init__(self, *verifiers: CompletionVerifier) -> None:
        self.verifiers = tuple(verifiers)

    def verify(self, context: AgentContext) -> CompletionEvidence:
        applicable_results: list[CompletionEvidence] = []
        for verifier in self.verifiers:
            evidence = verifier.verify(context)
            if evidence.complete:
                return evidence
            if evidence.applicable:
                applicable_results.append(evidence)
        if applicable_results:
            chosen = next(
                (
                    item
                    for item in applicable_results
                    if item.recommended_action is not None
                ),
                applicable_results[0],
            )
            return CompletionEvidence(
                False,
                chosen.message,
                applicable=True,
                recommended_action=chosen.recommended_action,
                recommended_arguments=chosen.recommended_arguments,
            )
        return CompletionEvidence(False, applicable=False)


class RecentFileNotepadVerifier:
    """Verify a recent-file discovery -> clipboard -> Notepad -> window task."""

    def verify(self, context: AgentContext) -> CompletionEvidence:
        expected = context.store.get("expected_text", None)
        expected_source = context.store.get("expected_source_path", None)
        target_bounds = context.store.get("target_window_bounds", None)
        source_dir = context.store.get("source_dir", None)
        if expected is None or expected_source is None or target_bounds is None or source_dir is None:
            return CompletionEvidence(False, applicable=False)

        goal = context.goal.casefold()
        if "most recent" not in goal or "notepad" not in goal or "clipboard" not in goal:
            return CompletionEvidence(False, applicable=False)

        expected_source_norm = str(expected_source).casefold()
        recent_found = False
        source_read = False
        clipboard_written = False
        clipboard_verified = False
        notepad_opened = False
        notepad_activated = False
        pasted = False
        moved = False
        bounds_verified = False
        process_verified = False

        for obs in context.observations:
            if not obs.success:
                continue

            if obs.action == "files.list_recent":
                files = obs.data.get("files", [])
                if files:
                    recent_found = str(files[0].get("path", "")).casefold() == expected_source_norm

            elif obs.action == "files.read_text":
                path = str(obs.data.get("path", "")).casefold()
                actual = obs.data.get("content", obs.data.get("text"))
                source_read = path == expected_source_norm and actual == expected

            elif obs.action == "clipboard.write":
                clipboard_written = int(obs.data.get("characters", -1)) == len(str(expected))

            elif obs.action == "clipboard.read":
                clipboard_verified = str(obs.data.get("text", "")).strip() == str(expected)

            elif obs.action == "system.open_app":
                app = str(obs.data.get("app", "")).casefold()
                command = str(obs.data.get("command", "")).casefold()
                notepad_opened = "notepad" in app or "notepad" in command

            elif obs.action == "system.activate_window":
                notepad_activated = "notepad" in str(obs.data.get("title", "")).casefold()

            elif obs.action == "desktop.hotkey":
                keys = tuple(str(item).casefold() for item in obs.data.get("keys", ()))
                pasted = keys == ("ctrl", "v")

            elif obs.action == "system.move_resize_window":
                moved = "notepad" in str(obs.data.get("title", "")).casefold()

            elif obs.action == "system.window_bounds":
                expected_bounds = dict(target_bounds)
                bounds_verified = (
                    "notepad" in str(obs.data.get("title", "")).casefold()
                    and abs(int(obs.data.get("x", -9999)) - int(expected_bounds["x"])) <= 20
                    and abs(int(obs.data.get("y", -9999)) - int(expected_bounds["y"])) <= 20
                    and abs(int(obs.data.get("width", -9999)) - int(expected_bounds["width"])) <= 30
                    and abs(int(obs.data.get("height", -9999)) - int(expected_bounds["height"])) <= 30
                )

            elif obs.action == "system.process_info":
                process_verified = (
                    str(obs.data.get("process", "")).casefold() == "notepad.exe"
                    and obs.data.get("running") is True
                )

        complete = all((
            recent_found,
            source_read,
            clipboard_written,
            clipboard_verified,
            notepad_opened,
            notepad_activated,
            pasted,
            moved,
            bounds_verified,
            process_verified,
        ))
        if complete:
            return CompletionEvidence(
                True,
                "Goal verified: the newest source file was discovered and read, its exact text was "
                "placed on the clipboard and pasted into activated Notepad, the Notepad window was "
                "moved/resized to the requested bounds, and the running process was confirmed.",
                applicable=True,
            )

        checks = {
            "recent-file discovery": recent_found,
            "source content read": source_read,
            "clipboard write": clipboard_written,
            "clipboard verification": clipboard_verified,
            "Notepad launch": notepad_opened,
            "Notepad activation": notepad_activated,
            "paste action": pasted,
            "window move/resize": moved,
            "window-bounds verification": bounds_verified,
            "Notepad process verification": process_verified,
        }
        missing = [name for name, passed in checks.items() if not passed]

        recommendation: tuple[str, dict[str, object]] | None = None
        if not recent_found:
            recommendation = (
                "files.list_recent",
                {"path": str(source_dir), "recursive": False, "limit": 10},
            )
        elif not source_read:
            recommendation = (
                "files.read_text",
                {"path": str(expected_source)},
            )
        elif not clipboard_written:
            recommendation = (
                "clipboard.write",
                {"text": str(expected)},
            )
        elif not clipboard_verified:
            recommendation = ("clipboard.read", {})
        elif not notepad_opened:
            recommendation = ("system.open_app", {"app": "notepad"})
        elif not notepad_activated:
            recommendation = ("system.activate_window", {"title": "Notepad"})
        elif not pasted:
            recommendation = ("desktop.hotkey", {"keys": ["ctrl", "v"]})
        elif not moved:
            bounds = dict(target_bounds)
            recommendation = (
                "system.move_resize_window",
                {
                    "title": "Notepad",
                    "x": int(bounds["x"]),
                    "y": int(bounds["y"]),
                    "width": int(bounds["width"]),
                    "height": int(bounds["height"]),
                },
            )
        elif not bounds_verified:
            recommendation = ("system.window_bounds", {"title": "Notepad"})
        elif not process_verified:
            recommendation = ("system.process_info", {"process": "notepad"})

        return CompletionEvidence(
            False,
            "Required deterministic evidence is still missing: " + ", ".join(missing) + ".",
            applicable=True,
            recommended_action=recommendation[0] if recommendation else None,
            recommended_arguments=recommendation[1] if recommendation else None,
        )


class ConversationalWebActionVerifier:
    """Complete a conversational web turn after its structured web action succeeds.

    The web tool itself may return sparse evidence; answer-quality checks happen in
    the conversation layer. This verifier prevents the agent from escaping into
    browser/desktop actions or asking unnecessary follow-up questions after the
    requested live lookup has already run.
    """

    def verify(self, context: AgentContext) -> CompletionEvidence:
        allowed = context.store.get("conversation_web_actions", None)
        if not allowed:
            return CompletionEvidence(False, applicable=False)
        expected = {str(item) for item in allowed}
        plan = context.store.get("conversation_web_plan", None)
        for observation in context.observations:
            if observation.success and observation.action in expected:
                return CompletionEvidence(
                    True,
                    f"Structured web lookup completed with {observation.action}.",
                    applicable=True,
                )

        recommended_action = None
        recommended_arguments = None
        if isinstance(plan, dict):
            candidate = str(plan.get("action", ""))
            candidate_args = plan.get("arguments", {})
            if candidate in expected and isinstance(candidate_args, dict):
                recommended_action = candidate
                recommended_arguments = dict(candidate_args)

        return CompletionEvidence(
            False,
            "A structured web lookup is still required before answering.",
            applicable=True,
            recommended_action=recommended_action,
            recommended_arguments=recommended_arguments,
        )
