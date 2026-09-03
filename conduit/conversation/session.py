"""Multi-turn natural-language session over the General PC Agent."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass
from typing import Any

from conduit.core.models import ChatMessage, Role, ToolCall
from conduit.core.errors import ProviderError
from conduit.core.progress_watchdog import ProgressStalledError, run_with_progress_watchdog
from conduit.general_pc import GeneralPCAgent
from .search_planner import AIIntentRouter, AISearchPlanner, IntentPlan, SearchPlan
from .youtube_planner import AIYouTubeRouter, YouTubePlan
from .system_planner import AISystemRouter, SystemPlan
from .file_planner import AIFileRouter, FilePlan
from .code_planner import parse_code_intent
from conduit.code_helper import code_service, CodeHelperError
from conduit.dev_agent import DeveloperAgent, DeveloperAgentError, dev_service
from conduit.games import games_service, GamesError, DownloadState
from conduit.system_control import windows as _system_windows
from conduit.file_processing import file_service
from conduit.file_processing.common import FileProcessingError, DependencyUnavailable
from conduit.messaging import AIMessagingRouter, MessagingPlan
from conduit.observer import ScreenLocator
from conduit.memory import ShortTermSessionMemory, LongTermMemoryLearner, SessionRecapManager


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    user: str
    assistant: str


@dataclass(frozen=True, slots=True)
class DirectConversationReport:
    """Report shape for a turn answered directly by the active AI model."""

    status: Any
    success: bool = True
    iterations: int = 0
    final_message: str = "Answered directly by the active model."
    observations: tuple = ()


class _DirectStatus:
    value = "direct_answer"


class _WeatherBrowserStatus:
    value = "weather_browser"


class _YouTubeStatus:
    value = "youtube_action"


class _MessagingStatus:
    value = "messaging_action"


class _BrowserStatus:
    value = "browser_action"


class _SystemStatus:
    value = "system_action"


class _FileStatus:
    value = "file_action"


class _CodeStatus:
    value = "code_action"


class _DevStatus:
    value = "dev_action"


class _GamesStatus:
    value = "games_action"


class ConversationSession:
    """Preserve conversational context while each turn uses Conduit's agent loop."""

    def __init__(
        self,
        agent: GeneralPCAgent,
        *,
        max_history_turns: int = 6,
        max_observation_chars: int = 18_000,
    ) -> None:
        self.agent = agent
        self.max_history_turns = max(1, max_history_turns)
        self.max_observation_chars = max(2_000, max_observation_chars)
        self._messaging_context: dict[str, str] = {}
        self._file_context: dict[str, Any] = {}
        self._code_context: dict[str, Any] = {}
        self._dev_context: dict[str, Any] = {}
        self._preference_context: dict[str, Any] = {}
        self.dev_agent = DeveloperAgent(agent)

        # Complete current-session transcript lives only in RAM. It is never
        # written to the persistent memory database.
        self.session_memory = ShortTermSessionMemory()
        # Backward-compatible list-like history view. It does NOT duplicate the
        # transcript in RAM; all exact turns come from the temporary store.
        self.history = self.session_memory.history
        bridge = getattr(getattr(agent, "loop", None), "memory_bridge", None)
        self.memory_manager = getattr(bridge, "manager", None) if bridge is not None else None
        self.long_term_learner = (
            LongTermMemoryLearner(self.memory_manager) if self.memory_manager is not None else None
        )
        self.recap_manager = (
            SessionRecapManager(self.memory_manager) if self.memory_manager is not None else None
        )
        self.resume_context = ""
        if self.recap_manager is not None:
            try:
                self.resume_context = self.recap_manager.resume_context(consume=True)
                self.session_memory.resume_context = self.resume_context
            except Exception:
                self.resume_context = ""

    def clear(self) -> None:
        # Legacy tests/extensions may replace `history` with a normal list.
        history = getattr(self, "history", None)
        session_memory = getattr(self, "session_memory", None)
        if history is not None and not getattr(history, "store", None) is session_memory:
            try:
                history.clear()
            except Exception:
                pass
        self._messaging_context.clear()
        self._file_context.clear()
        self._code_context.clear()
        self._dev_context.clear()
        self._preference_context.clear()
        if session_memory is not None:
            session_memory.clear()



    def record_runtime_event(self, name: str, payload: Any) -> None:
        try:
            if isinstance(payload, dict):
                details = json.dumps(payload, ensure_ascii=False, default=str)
            else:
                details = str(payload)
            self.session_memory.add_event(name, details)
        except Exception:
            return

    def finalize_session(self) -> str:
        """Persist only a compact recap, then wipe the RAM transcript."""
        summary = ""
        if self.recap_manager is not None:
            try:
                summary = self.recap_manager.summarize_and_store(self.session_memory)
            except Exception:
                summary = ""
        self.session_memory.close()
        return summary

    @staticmethod
    def _artifact_paths_from_text(text: str) -> list[Path]:
        """Extract plausible local file paths from a Conduit response."""
        value = str(text or "")
        candidates: list[str] = []

        # Windows paths, including spaces, ending in a common file extension.
        for match in re.finditer(
            r"(?i)([A-Za-z]:\\[^\r\n<>|?*]+?\.(?:py|js|ts|tsx|jsx|cpp|c|h|hpp|java|cs|go|rs|"
            r"txt|md|pdf|docx|xlsx|xls|csv|json|xml|pptx|png|jpg|jpeg|webp|gif|mp3|wav|mp4|mkv|mov|avi))"
            r"(?=[\s.,;:!?)]|$)",
            value,
        ):
            candidates.append(match.group(1).strip().rstrip(".,;:!?)]"))

        # Quoted absolute POSIX paths for cross-platform tests/development.
        for match in re.finditer(
            r"(?:^|[\s'\"])(/[^\r\n'\"]+?\.(?:py|js|ts|cpp|c|java|txt|md|pdf|docx|xlsx|csv|json|xml|pptx|png|jpg|jpeg|mp3|mp4))"
            r"(?=[\s'\".,;:!?)]|$)",
            value,
        ):
            candidates.append(match.group(1).strip().rstrip(".,;:!?)]"))

        result: list[Path] = []
        for raw in candidates:
            try:
                path = Path(raw).expanduser()
                if path.exists():
                    result.append(path.resolve())
            except Exception:
                continue
        return result

    def _remember_latest_artifact(self, assistant_text: str) -> None:
        context = self._ensure_file_context()
        paths = self._artifact_paths_from_text(assistant_text)
        if paths:
            context["last_artifact_path"] = str(paths[-1])

    def _latest_artifact_path(self) -> Path | None:
        """Resolve words such as 'that'/'it' to the latest file in this session."""
        # The file-processing service is authoritative for the most recently
        # generated/dropped/processed file and is updated by Code Helper too.
        try:
            active = file_service.get_active_file()
            if active is not None and active.path.exists():
                return active.path.resolve()
        except Exception:
            pass

        context = self._ensure_file_context()
        raw = str(context.get("last_artifact_path") or "").strip()
        if raw:
            try:
                candidate = Path(raw).expanduser()
                if candidate.exists():
                    return candidate.resolve()
            except Exception:
                pass

        # Last-resort exact-session lookup: scan recent Conduit answers backwards.
        try:
            for turn in reversed(self.session_memory.recent_turns(20)):
                paths = self._artifact_paths_from_text(turn.assistant)
                if paths:
                    return paths[-1]
        except Exception:
            pass
        return None

    @staticmethod
    def _vscode_executable() -> str | None:
        for name in ("code.cmd", "code.exe", "code"):
            hit = shutil.which(name)
            if hit:
                return hit
        if os.name == "nt":
            candidates = [
                Path(os.environ.get("LOCALAPPDATA", ""))/"Programs"/"Microsoft VS Code"/"Code.exe",
                Path(os.environ.get("PROGRAMFILES", ""))/"Microsoft VS Code"/"Code.exe",
                Path(os.environ.get("PROGRAMFILES(X86)", ""))/"Microsoft VS Code"/"Code.exe",
            ]
            for candidate in candidates:
                if str(candidate) and candidate.exists():
                    return str(candidate)
        return None

    @staticmethod
    def _is_delete_recent_artifact(message: str) -> bool:
        lower = " ".join(str(message or "").casefold().split())
        if not re.search(r"\b(?:delete|remove)\b", lower):
            return False
        if re.search(r"\b(?:project|folder|directory)\b", lower):
            return False
        return bool(
            re.search(
                r"\b(?:that|it|this|file|latest file|last file|generated file|recent file)\b",
                lower,
            )
        )

    def _delete_recent_artifact(self):
        target = self._latest_artifact_path()
        if target is None:
            answer = (
                "I don't have a recent file in this conversation to delete. "
                "Generate, process, or drop a file first."
            )
            return answer, DirectConversationReport(
                status=_FileStatus(), success=False, final_message=answer
            )
        if target.is_dir():
            answer = (
                f"{target.name} is a folder. I won't recursively delete a folder from "
                "the conversational 'that file' shortcut."
            )
            return answer, DirectConversationReport(
                status=_FileStatus(), success=False, final_message=answer
            )
        try:
            name = target.name
            target.unlink()
            context = self._ensure_file_context()
            if str(context.get("last_artifact_path") or "") == str(target):
                context.pop("last_artifact_path", None)
            answer = f"Deleted {name}."
            return answer, DirectConversationReport(
                status=_FileStatus(), success=True, final_message=answer
            )
        except Exception as exc:
            answer = f"I found {target.name}, but couldn't delete it: {exc}"
            return answer, DirectConversationReport(
                status=_FileStatus(), success=False, final_message=answer
            )

    @staticmethod
    def _is_open_recent_artifact_in_vscode(message: str) -> bool:
        lower = " ".join(str(message or "").casefold().split())
        if not re.search(r"\b(?:vscode|vs code|visual studio code)\b", lower):
            return False
        if not re.search(r"\bopen\b", lower):
            return False
        if re.search(r"\bproject\b", lower):
            return False
        return bool(
            re.search(r"\b(?:that|it|this|file|latest file|last file|generated file)\b", lower)
        )

    def _open_recent_artifact_in_vscode(self):
        target = self._latest_artifact_path()
        if target is None:
            answer = (
                "I don't have a recent file in this conversation to open in VS Code. "
                "Generate, process, or drop a file first."
            )
            return answer, DirectConversationReport(
                status=_CodeStatus(), success=False, final_message=answer
            )

        executable = self._vscode_executable()
        if not executable:
            answer = "Visual Studio Code is not installed or its executable could not be located."
            return answer, DirectConversationReport(
                status=_CodeStatus(), success=False, final_message=answer
            )

        try:
            cwd = target if target.is_dir() else target.parent
            subprocess.Popen(
                [executable, str(target)],
                cwd=str(cwd),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            answer = f"I found {target.name}, but couldn't open it in VS Code: {exc}"
            return answer, DirectConversationReport(
                status=_CodeStatus(), success=False, final_message=answer
            )

        answer = f"Opened {target.name} in Visual Studio Code."
        return answer, DirectConversationReport(
            status=_CodeStatus(), success=True, final_message=answer
        )

    def _preferred_directory(self, scope: str) -> str:
        if self.memory_manager is None:
            return ""
        try:
            return self.memory_manager.directive(scope, "output_directory")
        except Exception:
            return ""

    def _memory_bored_rewrite(self, text: str) -> str:
        if self.memory_manager is None:
            return text
        lower = " ".join(text.casefold().split())
        first = lower in {"i'm bored", "im bored", "i am bored", "bored", "i'm bored conduit", "im bored conduit"}
        next_one = any(x in lower for x in ("this is boring", "something else", "another one", "play something else", "still bored"))
        if not (first or next_one):
            return text
        try:
            channels = self.memory_manager.top_behaviors("youtube_channel", limit=8)
        except Exception:
            channels = ()
        if not channels:
            return text
        index = 0 if first else int(self._preference_context.get("bored_channel_index", 0)) + 1
        index = index % len(channels)
        self._preference_context["bored_channel_index"] = index
        channel = channels[index].value
        return f"play the latest video from {channel} on youtube"

    async def interrupt(self, *, reason: str = "User interrupted the current task.") -> None:
        """Broadcast a cooperative interrupt without destroying conversation state.

        Future voice/TTS modules can subscribe to ``speech.stop``; agent/tool/UI
        layers can subscribe to ``conversation.interrupted``.
        """
        events = getattr(self.agent, "events", None)
        if events is not None and hasattr(events, "emit"):
            await events.emit(
                "conversation.interrupted",
                source="ConversationSession",
                payload={"reason": reason},
            )
            await events.emit(
                "speech.stop",
                source="ConversationSession",
                payload={"reason": reason},
            )

    async def ask(self, user_message: str) -> tuple[str, Any]:
        clean = " ".join(user_message.split())
        if not clean:
            raise ValueError("Message cannot be empty.")
        original_clean = clean
        clean = self._memory_bored_rewrite(clean)

        if self.long_term_learner is not None:
            remembered = self.long_term_learner.remember_explicit_directive(original_clean)
            if remembered is not None:
                scope, key, value = remembered["scope"], remembered["key"], remembered["value"]
                if key == "output_directory":
                    answer = f"Remembered. I will use {value} as the default save location for generated code files and coding projects unless you specify a different path in the current request."
                else:
                    answer = f"Remembered. I'll follow this {scope} preference: {value}"
                report = DirectConversationReport(status=_DirectStatus(), success=True, final_message=answer)
                self._remember_turn(original_clean, answer)
                return answer, report

        recall_answer = self._session_recall_answer(clean)
        if recall_answer is not None:
            report = DirectConversationReport(
                status=_DirectStatus(),
                success=True,
                final_message=recall_answer,
            )
            self._remember_turn(original_clean, recall_answer)
            return recall_answer, report

        needs_history = self._message_needs_history(clean)
        resolved_request = self._resolved_request_text(clean, needs_history)

        pending_dev_plan = self._dev_context.get("pending_plan")
        if pending_dev_plan and clean.casefold() in {
            "yes", "y", "build it", "create it", "build", "create",
            "go ahead", "do it", "continue", "proceed"
        }:
            self._dev_context.pop("pending_plan", None)
            request = str(pending_dev_plan.get("request") or "")
            plan = pending_dev_plan.get("plan")
            path = str(pending_dev_plan.get("path") or "")
            try:
                files = await self.dev_agent.generate_project_files(request, plan)
                root = dev_service.create_from_files(
                    project_name=plan.name,
                    files=files,
                    plan=plan,
                    path=path,
                    base_dir=("" if path else self._preferred_directory("code")),
                )
                info = dev_service.inspect(root)
                answer = (
                    f"Created multi-file project '{plan.name}' at {root}.\n"
                    f"Generated {len(info.files)} project file(s)."
                )
                if info.entry_point:
                    answer += f"\nEntry point: {info.entry_point}."
                if info.dependency_files:
                    answer += (
                        "\nThis project has dependency metadata. "
                        "Say 'install project dependencies' if you want me to install them."
                    )
                answer += (
                    "\nYou can now ask me to inspect, modify, test, run, debug, "
                    "or open this project in VS Code."
                )
                report = DirectConversationReport(
                    status=_DevStatus(), success=True, final_message=answer
                )
            except Exception as exc:
                answer = f"I couldn't create the planned project: {exc}"
                report = DirectConversationReport(
                    status=_DevStatus(), success=False, final_message=answer
                )
            self._remember_turn(original_clean, answer)
            return answer, report

        if pending_dev_plan and clean.casefold() in {
            "no", "n", "cancel", "stop", "don't build", "do not build"
        }:
            self._dev_context.pop("pending_plan", None)
            answer = "Project creation cancelled. I kept the plan in the conversation history."
            report = DirectConversationReport(
                status=_DevStatus(), success=True, final_message=answer
            )
            self._remember_turn(original_clean, answer)
            return answer, report

        pending_dev_install = self._dev_context.get("pending_install")
        if pending_dev_install and clean.casefold() in {"yes","y","install","confirm"}:
            self._dev_context.pop("pending_install", None)
            result = dev_service.install_dependencies(
                pending_dev_install.get("path") or None,
                timeout=300.0,
            )
            self._dev_context["last_result"] = result
            answer = result.message
            if result.stdout.strip():
                answer += f"\n\nOutput:\n{result.stdout.strip()}"
            if result.stderr.strip():
                answer += f"\n\nError output:\n{result.stderr.strip()}"
            report = DirectConversationReport(
                status=_DevStatus(), success=result.success, final_message=answer
            )
            self._remember_turn(original_clean, answer)
            return answer, report
        if pending_dev_install and clean.casefold() in {"no","n","cancel"}:
            self._dev_context.pop("pending_install", None)
            answer = "Project dependency installation cancelled."
            report = DirectConversationReport(
                status=_DevStatus(), success=True, final_message=answer
            )
            self._remember_turn(original_clean, answer)
            return answer, report

        pending_install = self._code_context.get("pending_install")
        if pending_install and clean.casefold() in {"yes","y","install","confirm"}:
            self._code_context.pop("pending_install", None)
            result = code_service.install_dependency(pending_install["package"], language=pending_install["language"])
            answer = result.message
            if result.stdout.strip(): answer += f"\n\nOutput:\n{result.stdout.strip()}"
            if result.stderr.strip(): answer += f"\n\nError output:\n{result.stderr.strip()}"
            report = DirectConversationReport(status=_CodeStatus(), success=result.success, final_message=answer)
            self._remember_turn(original_clean, answer)
            return answer, report
        if pending_install and clean.casefold() in {"no","n","cancel"}:
            self._code_context.pop("pending_install", None)
            answer = "Dependency installation cancelled."
            report = DirectConversationReport(status=_CodeStatus(), success=True, final_message=answer)
            self._remember_turn(original_clean, answer)
            return answer, report

        pending_file = await self._continue_pending_file_operation(clean)
        if pending_file is not None:
            answer, report = pending_file
            self._remember_turn(original_clean, answer)
            return answer, report

        # Messaging uses a dedicated recipient/draft/confirmation workflow.
        if self._could_be_messaging_request(clean):
            messaging_plan = await self._make_messaging_plan(clean, needs_history=needs_history)
            if messaging_plan is not None:
                answer, report = await self._execute_messaging_plan(clean, messaging_plan)
                self._remember_turn(original_clean, answer)
                return answer, report

        # Steam/Epic game management is deterministic and launcher-aware.
        # Route it before generic browser/system handling so commands such as
        # "update Apex Legends" or "launch Fortnite" never become generic app
        # launches or browser searches.
        if self._could_be_games_request(clean):
            games_result = await self._execute_games_request(clean)
            if games_result is not None:
                answer, report = games_result
                self._remember_turn(original_clean, answer)
                return answer, report

        # Real-browser commands are deterministic. Route them before YouTube
        # and web research so phrases such as "open youtube in chrome" mean
        # "open the YouTube website in Chrome", not "choose a YouTube content
        # action". Likewise, "search X in my browser" must visibly search in the
        # user's real browser rather than silently becoming web.search.
        if self._could_be_browser_control_request(clean):
            browser_result = await self._execute_browser_control_request(clean)
            if browser_result is not None:
                answer, report = browser_result
                self._remember_turn(original_clean, answer)
                return answer, report

        # YouTube has a dedicated structured action pack. Route it before the
        # generic browser/PC planner so visible playback can never accidentally
        # fall back to managed Chromium.
        if self._could_be_youtube_request(clean):
            youtube_plan = await self._make_youtube_plan(
                clean,
                needs_history=needs_history,
            )
            if youtube_plan is not None:
                answer, report = await self._execute_youtube_plan(
                    clean,
                    youtube_plan,
                )
                self._remember_turn(original_clean, answer)
                return answer, report

        # Resolve "delete that file" against the most recent conversational
        # artifact before generic filesystem/system routing.
        if self._is_delete_recent_artifact(clean):
            answer, report = self._delete_recent_artifact()
            self._remember_turn(original_clean, answer)
            return answer, report

        # Resolve conversational file pronouns before the project developer
        # agent. "open that in VS Code" means the latest file, not a project.
        if self._is_open_recent_artifact_in_vscode(clean):
            answer, report = self._open_recent_artifact_in_vscode()
            self._remember_turn(original_clean, answer)
            return answer, report

        if self._could_be_dev_request(clean):
            dev_result = await self._execute_dev_request(clean)
            if dev_result is not None:
                answer, report = dev_result
                self._remember_turn(original_clean, answer)
                return answer, report

        if self._could_be_code_request(clean):
            code_result = await self._execute_code_request(clean)
            if code_result is not None:
                answer, report = code_result
                self._remember_turn(original_clean, answer)
                return answer, report

        if self._could_be_file_processing_request(clean):
            file_result = await self._execute_file_processing_request(clean)
            if file_result is not None:
                answer, report = file_result
                self._remember_turn(original_clean, answer)
                return answer, report

        # Hybrid structured system routing:
        # common phrases are instant/deterministic; unusual natural language is
        # translated by the active model into the SAME verified system.* tools.
        if self._could_be_system_control_request(clean):
            system_result = await self._execute_system_control_request(clean)
            if system_result is None:
                system_plan = await self._make_system_plan(
                    clean,
                    needs_history=needs_history,
                )
                if system_plan is not None:
                    system_result = await self._execute_system_plan(system_plan)
            if system_result is not None:
                answer, report = system_result
                self._remember_turn(original_clean, answer)
                return answer, report

        intent_plan = await self._make_intent_plan(
            clean,
            needs_history=needs_history,
        )

        # Current/upcoming weather is intentionally a visible browser experience.
        # Reuse the managed browser when it exists; otherwise start it.
        if self._is_weather_browser_lookup(clean):
            answer = await self._open_weather_in_browser(
                intent_plan.normalized_request or clean
            )
            report = DirectConversationReport(
                status=_WeatherBrowserStatus(),
                final_message=answer,
            )
            self._remember_turn(original_clean, answer)
            return answer, report

        # Reliability guard: explicit evidence/live language is authoritative.
        # The model may normalize the request, but it cannot downgrade a request
        # for sources, studies, research, news, weather, current prices, etc. to
        # an unsupported direct answer.
        forced_web_actions = self._required_web_actions(clean)
        if forced_web_actions and not intent_plan.browser_requested:
            forced_action = next(iter(forced_web_actions))
            route = (
                "hybrid"
                if (
                    forced_action == "web.compare"
                    or self._sources_or_verification_requested(clean)
                )
                else "tool"
            )
            intent_plan = IntentPlan(
                route=route,
                web_needed=True,
                browser_requested=False,
                normalized_request=intent_plan.normalized_request or clean,
                intent=intent_plan.intent or "evidence_required",
            )
        else:
            route = intent_plan.route

        if route == "direct":
            answer = await self._direct_answer(
                clean,
                include_history=bool(self.history) or needs_history,
            )
            report = DirectConversationReport(status=_DirectStatus())
            self._remember_turn(original_clean, answer)
            return answer, report

        search_plan: SearchPlan | None = None
        action_policy = None
        evidence_hypothesis = ""

        if intent_plan.web_needed and not intent_plan.browser_requested:
            if route == "hybrid":
                evidence_hypothesis = await self._build_evidence_hypothesis(
                    clean,
                    include_history=bool(self.history) or needs_history,
                )
            search_plan = await self._make_search_plan(
                intent_plan.normalized_request or clean,
                needs_history=needs_history,
                allowed_actions=forced_web_actions or None,
                evidence_hypothesis=evidence_hypothesis,
            )
            action_policy = {search_plan.action}
            goal = self._goal_from_search_plan(
                clean,
                search_plan,
                include_history=bool(self.history) or needs_history,
            )
            web_actions = {search_plan.action}
            events = getattr(self.agent, "events", None)
            if events is not None and hasattr(events, "emit"):
                await events.emit(
                    "conversation.search.planned",
                    source="ConversationSession",
                    payload={
                        "action": search_plan.action,
                        "intent": search_plan.intent,
                        "subject": search_plan.subject,
                        "rewritten_request": search_plan.rewritten_request,
                        "arguments": dict(search_plan.arguments),
                        "answer_style": search_plan.answer_style,
                    },
                )
        else:
            goal = self._goal_with_context(
                clean,
                include_history=bool(self.history) or needs_history,
            )
            web_actions = set()

        report = await self.agent.run(
            goal,
            initial_variables={
                "conversation_user_message": clean,
                "conversation_resolved_request": resolved_request,
                "conversation_history": (
                    [
                        {"user": turn.user, "assistant": turn.assistant}
                        for turn in self.session_memory.recent_turns(self.max_history_turns)
                    ]
                    if needs_history
                    else []
                ),
                "conversation_route": route,
                "conversation_intent_plan": {
                    "route": intent_plan.route,
                    "web_needed": intent_plan.web_needed,
                    "browser_requested": intent_plan.browser_requested,
                    "normalized_request": intent_plan.normalized_request,
                    "intent": intent_plan.intent,
                },
                "conversation_web_actions": sorted(web_actions),
                "conversation_web_plan": search_plan.to_dict() if search_plan else None,
                "conversation_browser_forbidden": bool(web_actions),
                "conversation_history_used": needs_history,
            },
            allowed_actions=action_policy,
        )

        if route == "hybrid" and self._strict_verification_requested(clean):
            answer = await self._compose_answer(
                clean,
                report,
                search_plan=search_plan,
                evidence_hypothesis=evidence_hypothesis,
            )
        elif route == "hybrid":
            answer = await self._compose_hybrid_answer(
                clean,
                report,
                search_plan=search_plan,
                evidence_hypothesis=evidence_hypothesis,
            )
        else:
            answer = await self._compose_answer(
                clean,
                report,
                search_plan=search_plan,
                evidence_hypothesis=evidence_hypothesis,
            )

        self._remember_turn(original_clean, answer)
        return answer, report


    def _active_code_path(self):
        return code_service.active_code_file()

    @staticmethod
    def _games_platform_from_text(message: str) -> str:
        lower = message.casefold()
        if re.search(r"\bepic(?: games)?\b", lower):
            return "epic"
        if re.search(r"\bsteam\b", lower):
            return "steam"
        return ""

    @staticmethod
    def _games_strip_name(message: str) -> str:
        value = str(message or "").strip()
        patterns = [
            r"(?i)\b(?:and\s+then\s+|then\s+)?(?:shut\s*down|shutdown|turn\s+off)\b.*$",
            r"(?i)\bwhen\s+(?:it|the\s+(?:game|update|download))\s+(?:is\s+)?(?:done|finished|complete).*?$",
            r"(?i)\bonce\s+(?:it|the\s+(?:game|update|download))\s+(?:is\s+)?(?:done|finished|complete).*?$",
            r"(?i)\bafter\s+(?:it|the\s+(?:game|update|download))\s+(?:is\s+)?(?:done|finished|complete).*?$",
        ]
        for pattern in patterns:
            value = re.sub(pattern, "", value).strip()

        value = re.sub(
            r"(?i)^\s*(?:please\s+)?(?:update|install|download|launch|start|play|"
            r"check|show|inspect|schedule|cancel)\s+",
            "",
            value,
        ).strip()
        value = re.sub(
            r"(?i)^\s*(?:the\s+)?(?:download\s+status|update\s+status|status)\s+(?:of|for)\s+",
            "",
            value,
        ).strip()
        value = re.sub(
            r"(?i)\b(?:on|from|in|through|using)\s+(?:steam|epic(?:\s+games)?(?:\s+launcher)?)\b",
            "",
            value,
        ).strip()
        value = re.sub(
            r"(?i)\b(?:game|please)\b\s*$",
            "",
            value,
        ).strip()
        value = re.sub(
            r"(?i)\b(?:at|for)\s+(?:today\s+|tomorrow\s+)?"
            r"(?:\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm))\b.*$",
            "",
            value,
        ).strip()
        # Remove schedule/cancel-update wording remaining at the front.
        value = re.sub(
            r"(?i)^\s*(?:the\s+)?(?:scheduled\s+)?(?:update\s+for\s+|update\s+of\s+)",
            "",
            value,
        ).strip()
        value = re.sub(r"(?i)\s+update\s*$", "", value).strip()
        value = re.sub(r"(?i)^scheduled\s+", "", value).strip()
        value = re.sub(r"(?i)\s+and\s*$", "", value).strip()
        return value.strip(" .,-")

    @staticmethod
    def _games_shutdown_after_completion(message: str) -> bool:
        lower = " ".join(message.casefold().split())
        wants_shutdown = bool(
            re.search(r"\b(?:shut\s*down|shutdown|turn\s+off)\b", lower)
        )
        completion = bool(
            re.search(
                r"\b(?:when|once|after)\b.*\b(?:done|finish(?:ed|es)?|complete(?:d|s)?|download(?:ed|ing)?|update(?:d|ing)?)\b",
                lower,
            )
            or re.search(r"\bafter\s+(?:the\s+)?(?:download|update)\b", lower)
        )
        return wants_shutdown and completion

    @staticmethod
    def _games_schedule_time(message: str) -> str:
        from datetime import datetime, timedelta

        lower = message.casefold()
        date_prefix = ""
        if "tomorrow" in lower:
            date_prefix = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d ")

        match = re.search(r"\b(\d{1,2}):(\d{2})\b", lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{date_prefix}{hour:02d}:{minute:02d}".strip()

        match = re.search(r"\b(\d{1,2})\s*(am|pm)\b", lower)
        if match:
            hour = int(match.group(1))
            if 1 <= hour <= 12:
                if match.group(2) == "am":
                    hour = 0 if hour == 12 else hour
                else:
                    hour = hour if hour == 12 else hour + 12
                return f"{date_prefix}{hour:02d}:00".strip()

        # Explicit YYYY-MM-DD HH:MM.
        match = re.search(r"\b(\d{4}-\d{2}-\d{2})\s+(\d{1,2}):(\d{2})\b", lower)
        if match:
            return f"{match.group(1)} {int(match.group(2)):02d}:{int(match.group(3)):02d}"
        return ""

    def _could_be_games_request(self, message: str) -> bool:
        lower = " ".join(message.casefold().split())

        explicit = (
            "installed games", "games installed", "list my games", "list games",
            "game library", "steam games", "epic games",
            "download status", "update status", "game update",
            "update game", "schedule update", "scheduled update",
            "cancel schedule", "cancel scheduled",
        )
        if any(term in lower for term in explicit):
            return True
        if re.search(r"\bschedule\b.*\bupdate\b", lower):
            return True
        if re.search(r"\bcancel\b.*\b(?:schedule|scheduled)\b", lower):
            return True

        if re.search(r"\b(?:update|install|launch|start|play)\b", lower):
            if any(x in lower for x in (" steam", " epic", "game")):
                return True
            # Recognize an installed title even when the user simply says
            # "launch Apex Legends" or "play Fortnite".
            try:
                query = self._games_strip_name(message)
                if query:
                    games_service.find_game(query)
                    return True
            except Exception:
                pass

        if any(term in lower for term in ("how much is left", "how much left", "still downloading", "download finished", "update finished")):
            return games_service.last_game() is not None

        return False

    async def _activate_steam_scheduled_update(self, game):
        """Activate Steam's per-game Download Now control and verify the state.

        Steam's URI protocol can open Downloads but does not reliably force an
        already-installed game's scheduled update. This uses Conduit's existing
        structured desktop vision and bounded desktop controller. No fixed
        screen coordinates are used.
        """
        import asyncio as _asyncio

        router = getattr(self.agent, "router", None)
        observer = getattr(router, "observer", None)
        desktop = getattr(router, "desktop", None)
        if observer is None or desktop is None:
            return (
                False,
                "Steam has the update scheduled, but the current model cannot "
                "visually inspect Steam safely. Switch to a vision-capable Ollama "
                "model such as qwen2.5vl:7b or use Gemini, then try again.",
            )

        await _asyncio.sleep(1.5)

        try:
            analysis = await observer.analyze_structured(
                "Steam Downloads is open. Locate the row for "
                f"'{game.name}' and identify the clickable Download Now / "
                "download-arrow / update-now control on THAT SAME ROW. "
                "Do not choose a control belonging to any other game."
            )
        except Exception as exc:
            return False, f"I opened Steam Downloads but couldn't inspect its controls: {exc}"

        elements = [e for e in analysis.elements if e.visible and e.enabled]
        locator = ScreenLocator(analysis)

        row = None
        try:
            row = locator.find(game.name)
        except Exception:
            wanted = game.name.casefold()
            for element in elements:
                if wanted in f"{element.label} {element.text}".casefold():
                    row = element
                    break

        if row is None:
            return False, f"Steam Downloads opened, but I couldn't locate the {game.name} row."

        candidates = []
        for element in elements:
            role = element.role.casefold()
            if role not in {"button", "link", "image", "unknown"}:
                continue

            hay = f"{element.label} {element.text}".casefold()
            actionish = any(
                term in hay
                for term in (
                    "download", "update", "install", "download now",
                    "start download", "arrow down", "down arrow",
                )
            )
            gameish = game.name.casefold() in hay
            vertical_distance = abs(element.bounds.center_y - row.bounds.center_y)
            same_row = vertical_distance <= max(70, row.bounds.height * 2)

            if not same_row or (not actionish and not gameish):
                continue

            score = 0
            if gameish:
                score += 100
            if actionish:
                score += 60
            if element.bounds.center_x > row.bounds.center_x:
                score += 25
            score -= min(vertical_distance, 100)
            candidates.append((score, element))

        # Steam may expose the icon generically as just a button. If so, choose
        # only a button on the same row and to the right of the title.
        if not candidates:
            for element in elements:
                if element.role.casefold() not in {"button", "link"}:
                    continue
                vertical_distance = abs(element.bounds.center_y - row.bounds.center_y)
                if (
                    vertical_distance <= max(55, row.bounds.height * 2)
                    and element.bounds.center_x > row.bounds.center_x
                ):
                    score = 20 - min(vertical_distance, 20)
                    candidates.append((score, element))

        if not candidates:
            return (
                False,
                f"I found {game.name} in Steam Downloads but couldn't safely "
                "identify its Download Now button.",
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        target = candidates[0][1]

        try:
            x, y = target.center
            point = desktop.capture_point_to_desktop(
                x,
                y,
                capture_width=analysis.capture.width,
                capture_height=analysis.capture.height,
            )
            desktop.click(point.x, point.y)
        except Exception as exc:
            return False, f"I found the Steam update button but couldn't click it: {exc}"

        # Verify using Steam's own appmanifest rather than assuming the click.
        for _ in range(10):
            await _asyncio.sleep(0.6)
            status = games_service.download_status(game)
            if status.state in {
                DownloadState.DOWNLOADING,
                DownloadState.QUEUED,
                DownloadState.INSTALLING,
                DownloadState.VERIFYING,
                DownloadState.PAUSED,
            }:
                return True, (
                    f"Started the Steam update for {game.name}. "
                    f"Current state: {status.message}"
                )
            if status.state is DownloadState.COMPLETE and status.update_available is False:
                return True, f"{game.name} is now up to date."

        return (
            False,
            f"I clicked {game.name}'s Steam download control, but Steam did not "
            "confirm that the update started.",
        )

    async def _execute_games_request(self, current: str):
        lower = " ".join(current.casefold().split())
        platform = self._games_platform_from_text(current)

        def report(message: str, success: bool = True):
            return message, DirectConversationReport(
                status=_GamesStatus(),
                success=success,
                final_message=message,
            )

        # List installed launcher-managed games.
        if (
            any(x in lower for x in ("list installed games", "list my games", "list games", "games installed"))
            or re.search(r"\bwhat\s+games\b.*\binstalled\b", lower)
        ):
            try:
                games = games_service.list_installed()
            except Exception as exc:
                return report(f"I couldn't inspect installed games: {exc}", False)
            if not games:
                return report("I couldn't find any installed Steam or Epic games.", False)
            lines = [
                f"- {game.name} — {game.platform.value.title()}"
                for game in games
            ]
            return report(
                f"Installed games ({len(games)}):\n" + "\n".join(lines)
            )

        # Follow-up status can refer to the last game.
        status_intent = bool(
            any(x in lower for x in (
                "download status", "update status", "how much is left",
                "how much left", "still downloading", "download finished",
                "update finished", "check download", "check update",
            ))
        )

        query = self._games_strip_name(current)
        game = None
        if status_intent and (
            not query
            or query.casefold() in {
                "how much is left", "how much left", "is it still downloading",
                "is the download finished", "is the update finished",
            }
        ):
            game = games_service.last_game()

        if game is None and not (
            re.search(r"\binstall\b", lower)
            and not any(g.name.casefold() in lower for g in games_service.list_installed())
        ):
            try:
                game = games_service.find_game(query or current, platform=platform)
            except Exception:
                game = None

        if status_intent:
            if game is None:
                return report("Tell me which installed game you want me to check.", False)
            try:
                status = games_service.download_status(game)
            except Exception as exc:
                return report(f"I couldn't read the download status: {exc}", False)

            message = f"{game.name}: {status.message}"
            if status.progress is not None:
                message += f" Progress: {status.progress:.1f}%."
            if status.bytes_downloaded is not None and status.bytes_total is not None:
                remaining = max(0, status.bytes_total - status.bytes_downloaded)
                message += f" Remaining bytes: {remaining:,}."
            return report(message)

        # Schedule / cancel schedule.
        if re.search(r"\bcancel\b.*\b(?:schedule|scheduled update)\b", lower):
            if game is None:
                return report("Tell me which installed game's scheduled update to cancel.", False)
            try:
                return report(games_service.cancel_schedule(game))
            except Exception as exc:
                return report(str(exc), False)

        if re.search(r"\bschedule\b.*\bupdate\b|\bupdate\b.*\b(?:at|tomorrow)\b", lower):
            if game is None:
                return report("Tell me which installed game to schedule.", False)
            when = self._games_schedule_time(current)
            if not when:
                return report(
                    "Tell me when to update it, for example 'schedule Apex Legends update at 23:30'.",
                    False,
                )
            try:
                return report(games_service.schedule_update(game, when=when))
            except Exception as exc:
                return report(str(exc), False)

        # Install may refer to a game not yet installed.
        if re.search(r"\binstall\b|\bdownload\b", lower) and not status_intent:
            install_query = query or current
            target_platform = platform or "steam"
            try:
                message = games_service.install(install_query, platform=target_platform)
                return report(message)
            except Exception as exc:
                return report(str(exc), False)

        # Update with optional one-shot shutdown-after-completion.
        if re.search(r"\bupdate\b", lower):
            if game is None:
                return report("I couldn't find that game in your installed Steam/Epic library.", False)
            wants_shutdown = self._games_shutdown_after_completion(current)
            try:
                message, before = games_service.update(game)
            except Exception as exc:
                return report(f"I couldn't start the game update: {exc}", False)

            if before.update_available is False and before.state is DownloadState.COMPLETE:
                if wants_shutdown:
                    message += " The PC will stay on because no download/update was started."
                return report(message)

            if game.platform.value == "steam":
                import asyncio as _asyncio

                active_states = {
                    DownloadState.DOWNLOADING,
                    DownloadState.QUEUED,
                    DownloadState.INSTALLING,
                    DownloadState.VERIFYING,
                    DownloadState.PAUSED,
                }

                async def verify_steam_state(attempts: int):
                    latest = None
                    for _ in range(attempts):
                        await _asyncio.sleep(0.65)
                        latest = games_service.download_status(game)
                        if latest.state in active_states:
                            return True, latest
                        if (
                            latest.state is DownloadState.COMPLETE
                            and latest.update_available is False
                        ):
                            return True, latest
                    return False, latest

                # Mark's updater also uses steam://update/<appid>. Keep that as
                # the first attempt, but if this Steam client leaves the game in
                # Scheduled/Unscheduled, fall back to the native Steam UI control.
                confirmed, verified = await verify_steam_state(8)

                if not confirmed:
                    uia_ok, _uia_message = await _asyncio.to_thread(
                        games_service.activate_steam_update_uia,
                        game,
                    )
                    if uia_ok:
                        confirmed, verified = await verify_steam_state(12)

                # Final fallback: Conduit's structured screen vision.
                if not confirmed:
                    visual_ok, _visual_message = await self._activate_steam_scheduled_update(game)
                    if visual_ok:
                        confirmed, verified = await verify_steam_state(12)

                if not confirmed:
                    games_service._launch_steam_url("steam://open/downloads")
                    return report(
                        f"Steam did not confirm that the update for {game.name} "
                        "started after the direct Steam update request and both "
                        "native/visual Steam controls. I opened Steam Downloads.",
                        False,
                    )

                if (
                    verified is not None
                    and verified.state is DownloadState.COMPLETE
                    and verified.update_available is False
                ):
                    message = f"No update available for {game.name}."
                else:
                    message = (
                        f"Started the Steam update for {game.name}. "
                        f"Current state: {verified.message if verified else 'active'}"
                    )

            if wants_shutdown:
                def shutdown_when_done(_game):
                    try:
                        _system_windows.shutdown_computer()
                    except Exception:
                        pass

                monitor_message = games_service.monitor_until_complete(
                    game,
                    on_complete=shutdown_when_done,
                    require_active_transition=True,
                )
                message += (
                    f" {monitor_message} The PC will shut down automatically only after "
                    "the launcher reports that this update has completed."
                )
            return report(message)

        # Launch/play installed game.
        if re.search(r"\b(?:launch|start|play|open)\b", lower):
            if game is None:
                return report("I couldn't find that game in your installed Steam/Epic library.", False)
            try:
                return report(games_service.launch(game))
            except Exception as exc:
                return report(f"I couldn't launch the game: {exc}", False)

        return None

    @staticmethod
    def _project_path_from_message(message: str) -> str:
        # Quoted Windows/absolute project folder path.
        quoted = re.search(r'["\']([A-Za-z]:\\[^"\']+|/[^\n"\']+)["\']', message)
        if quoted:
            return quoted.group(1).strip()
        windows = re.search(r'\b([A-Za-z]:\\[^\n]+)$', message)
        if windows:
            return windows.group(1).strip().rstrip(".")
        return ""

    def _could_be_dev_request(self, message: str) -> bool:
        lower = " ".join(message.casefold().split())
        active = dev_service.active_project()

        project_words = (
            "project", "multi-file", "multifile", "codebase", "repository", "repo",
            "vscode", "vs code", "project files", "project dependencies",
        )
        if any(word in lower for word in project_words):
            return True

        if active is not None:
            active_phrases = (
                "run the app", "run the application", "start the app", "start the application",
                "run tests", "run the tests", "install dependencies", "install the dependencies",
                "fix all errors", "fix the errors", "debug the app", "debug the application",
                "open in vscode", "open in vs code", "add this feature", "modify the app",
                "make sure it works", "test everything",
            )
            if any(x in lower for x in active_phrases):
                return True
        return False

    async def _execute_dev_request(self, current: str):
        lower = " ".join(current.casefold().split())
        explicit_path = self._project_path_from_message(current)

        async def dev_report(answer: str, success: bool = True):
            return answer, DirectConversationReport(
                status=_DevStatus(), success=success, final_message=answer
            )

        # PLAN only: no filesystem mutation.
        if re.search(r"(?i)\bplan\b", current) and any(
            x in lower for x in ("project","app","application","website","codebase")
        ):
            try:
                plan = await self.dev_agent.plan_project(current)
            except Exception as exc:
                return await dev_report(f"I couldn't plan the project: {exc}", False)
            files = "\n".join(
                f"- {item['path']}: {item['purpose']}" for item in plan.files
            )
            self._dev_context["pending_plan"] = {
                "request": current,
                "plan": plan,
                "path": explicit_path,
            }
            answer = (
                f"Project plan: {plan.name}\n"
                f"Language: {plan.language}"
                + (f"\nFramework: {plan.framework}" if plan.framework else "")
                + (f"\nEntry point: {plan.entry_point}" if plan.entry_point else "")
                + f"\n\nFiles:\n{files}"
                + (
                    f"\n\nDependencies: {', '.join(plan.dependencies)}"
                    if plan.dependencies else "\n\nDependencies: none planned."
                )
                + "\n\nBuild this planned project now? Type YES to create all files or NO to keep only the plan."
            )
            return await dev_report(answer)

        # CREATE a new multi-file project. The word project/multi-file keeps this
        # separate from the single-file code.generate workflow.
        create_intent = bool(
            re.search(r"(?i)\b(?:create|generate|build|make)\b", current)
            and any(x in lower for x in ("project","multi-file","multifile","codebase","website project","app project"))
        )
        if create_intent:
            try:
                root, plan = await self.dev_agent.create_project(
                    current,
                    path=explicit_path,
                    base_dir=("" if explicit_path else self._preferred_directory("code")),
                )
                info = dev_service.inspect(root)
            except Exception as exc:
                return await dev_report(f"I couldn't create the project: {exc}", False)
            answer = (
                f"Created multi-file project '{plan.name}' at {root}.\n"
                f"Generated {len(info.files)} project file(s)."
            )
            if info.entry_point:
                answer += f"\nEntry point: {info.entry_point}."
            if info.dependency_files:
                answer += (
                    "\nThis project has dependency metadata. "
                    "Say 'install project dependencies' if you want Conduit to install them."
                )
            answer += (
                "\nYou can now ask me to inspect, modify, test, run, debug, or open this project in VS Code."
            )
            return await dev_report(answer)

        # Adopt/inspect an explicit existing project path.
        if explicit_path:
            try:
                dev_service.set_active_project(explicit_path)
            except Exception as exc:
                return await dev_report(str(exc), False)

        active = dev_service.active_project()
        if active is None:
            return await dev_report(
                "No active multi-file project is set. Create a project first or provide its folder path.",
                False,
            )

        if re.search(r"(?i)\b(?:inspect|structure|list files|show files|what files)\b", current):
            try:
                info = dev_service.inspect(active)
            except Exception as exc:
                return await dev_report(f"I couldn't inspect the project: {exc}", False)
            files = "\n".join(f"- {x}" for x in info.files[:100])
            answer = (
                f"Project: {info.name}\nType: {info.kind.value}\nRoot: {info.root}\n"
                f"Entry point: {info.entry_point or 'not detected'}\n\nFiles:\n{files}"
            )
            return await dev_report(answer)

        if re.search(r"(?i)\binstall\b.*\b(?:dependencies|dependency|packages)\b", current):
            try:
                command, cwd = dev_service.dependency_install_command(active)
            except Exception as exc:
                return await dev_report(str(exc), False)
            self._dev_context["pending_install"] = {"path": str(active)}
            safe_display = " ".join(Path(arg).name if index == 0 else arg for index, arg in enumerate(command))
            answer = (
                f"Install this project's dependencies in {cwd}?\n"
                f"Command: {safe_display}\n"
                "Type YES to install or NO to cancel."
            )
            return await dev_report(answer, False)

        if re.search(r"(?i)\bopen\b.*\b(?:vscode|vs code|editor)\b", current):
            try:
                answer = dev_service.open_editor(active)
                return await dev_report(answer)
            except Exception as exc:
                return await dev_report(str(exc), False)

        if re.search(r"(?i)\b(?:run|execute|start)\b.*\b(?:tests?|test suite)\b|\btest the project\b", current):
            try:
                result = dev_service.run_tests(active)
                self._dev_context["last_result"] = result
            except Exception as exc:
                return await dev_report(f"I couldn't run project tests: {exc}", False)
            pieces = [result.message]
            if result.stdout.strip():
                pieces.append(f"Output:\n{result.stdout.strip()}")
            if result.stderr.strip():
                pieces.append(f"Error output:\n{result.stderr.strip()}")
            if not result.success:
                pieces.append(f"Error category: {result.category.value}.")
            return await dev_report("\n\n".join(pieces), result.success)

        if re.search(r"(?i)\b(?:run|execute|start)\b.*\b(?:project|app|application|website)\b", current):
            try:
                result = dev_service.run_project(active)
                self._dev_context["last_result"] = result
            except Exception as exc:
                return await dev_report(f"I couldn't run the project: {exc}", False)
            pieces = [result.message]
            if result.stdout.strip():
                pieces.append(f"Output:\n{result.stdout.strip()}")
            if result.stderr.strip():
                pieces.append(f"Error output:\n{result.stderr.strip()}")
            if not result.success:
                pieces.append(f"Error category: {result.category.value}.")
            return await dev_report("\n\n".join(pieces), result.success)

        if re.search(r"(?i)\b(?:analy[sz]e|explain)\b.*\b(?:error|failure)\b", current):
            result = self._dev_context.get("last_result")
            if result is None:
                return await dev_report(
                    "There is no captured project error yet. Run the project or its tests first.",
                    False,
                )
            try:
                answer = await self.dev_agent.analyze_error(
                    user_request=current,
                    result=result,
                )
                return await dev_report(answer)
            except Exception as exc:
                return await dev_report(f"I couldn't analyze the project error: {exc}", False)

        if re.search(r"(?i)\b(?:fix|debug|repair)\b", current) or "make sure it works" in lower:
            try:
                result, attempts = await self.dev_agent.repair_until_working(
                    current,
                    max_attempts=3,
                )
                self._dev_context["last_result"] = result
            except Exception as exc:
                return await dev_report(f"I couldn't repair the project: {exc}", False)
            if result.success:
                answer = (
                    f"Repaired and verified the project after {attempts} repair attempt(s)."
                )
                if result.stdout.strip():
                    answer += f"\n\nOutput:\n{result.stdout.strip()}"
                return await dev_report(answer)
            answer = (
                f"I couldn't fully repair the project after {attempts} attempt(s). "
                f"Last error category: {result.category.value}."
            )
            if result.stderr.strip():
                answer += f"\n\nError output:\n{result.stderr.strip()}"
            return await dev_report(answer, False)

        patch_intent = bool(
            re.search(r"(?i)\b(?:edit|modify|change|add|remove|implement|update|refactor)\b", current)
            and any(x in lower for x in ("project","app","application","website","feature","codebase"))
        )
        if patch_intent:
            try:
                written = await self.dev_agent.patch_project(current)
            except Exception as exc:
                return await dev_report(f"I couldn't modify the project: {exc}", False)
            names = ", ".join(str(x.relative_to(active)) for x in written)
            return await dev_report(
                f"Updated {len(written)} project file(s): {names}. "
                "Backups of replaced files were saved under .conduit_backups."
            )

        return None

    @classmethod
    def _could_be_code_request(cls, message: str) -> bool:
        active = code_service.active_code_file()
        intent = parse_code_intent(message, has_active_code=active is not None)
        return intent is not None

    async def _code_model_text(self, prompt: str, *, timeout: float | None = None) -> str:
        """Unlimited-duration coding request guarded by a 60-second progress watchdog."""

        async def emit_watchdog(snapshot):
            events = getattr(self.agent, "events", None)
            if events is not None and hasattr(events, "emit"):
                await events.emit(
                    "code.stage",
                    source="CodeHelper",
                    payload={
                        "stage": "provider_watchdog",
                        "elapsed_seconds": round(snapshot.elapsed_seconds, 1),
                        "seconds_since_progress": round(snapshot.seconds_since_progress, 1),
                        "progress_units": snapshot.progress_units,
                        "detail": snapshot.detail,
                        "missed_checks": snapshot.missed_checks,
                    },
                )

        async def request_once(heartbeat):
            provider = self.agent.loop.provider
            if hasattr(provider, "specialist_chat_with_progress"):
                return await provider.specialist_chat_with_progress(
                    [ChatMessage(Role.USER, prompt)],
                    model=self.agent.loop.model,
                    on_progress=heartbeat,
                )
            heartbeat(0, "request dispatched")
            response = await provider.specialist_chat(
                [ChatMessage(Role.USER, prompt)], model=self.agent.loop.model
            )
            heartbeat(max(1, len(response.text)), "response complete")
            return response

        try:
            response = await run_with_progress_watchdog(
                request_once,
                check_interval=60.0,
                initial_missed_checks=2,
                active_missed_checks=1,
                on_check=emit_watchdog,
            )
        except ProgressStalledError as exc:
            raise CodeHelperError(
                str(exc) + " Please try again or switch to a faster coding model."
            ) from exc
        except ProviderError as exc:
            recovered = await self.agent.recover_provider_error(exc)
            if not recovered:
                raise CodeHelperError(
                    "The AI provider became unavailable and the task was cancelled."
                ) from exc
            try:
                response = await run_with_progress_watchdog(
                    request_once,
                    check_interval=60.0,
                    initial_missed_checks=2,
                    active_missed_checks=1,
                    on_check=emit_watchdog,
                )
            except ProgressStalledError as stalled:
                raise CodeHelperError(
                    str(stalled) + " Please try again or switch to a faster coding model."
                ) from stalled
        return response.text.strip()

    @staticmethod
    def _code_language_instruction(language: str) -> str:
        return language if language and language != "unknown" else "the source file's language"

    async def _execute_code_request(self, current: str):
        active = code_service.active_code_file()
        intent = parse_code_intent(current, has_active_code=active is not None)
        if intent is None:
            return None

        async def emit(stage: str, **payload):
            events = getattr(self.agent, "events", None)
            if events is not None and hasattr(events, "emit"):
                await events.emit("code.stage", source="CodeHelper", payload={"stage": stage, **payload})

        if intent.action == "generate":
            language = intent.language or "python"
            provider_name = type(self.agent.loop.provider).__name__.replace("Provider", "") or "provider"
            model_name = str(self.agent.loop.model)

            await emit("generating", language=language, provider=provider_name, model=model_name)
            await emit("provider_request", provider=provider_name, model=model_name, watchdog_interval_seconds=60, overall_timeout="unlimited")

            prompt = (
                f"Generate a complete single-file {language} program for this request:\n{current}\n\n"
                "Return ONLY raw source code. No Markdown fences or explanation. "
                "The file must be complete, high quality, and internally consistent. "
                "Do not leave TODOs, pseudocode, placeholders, or omitted sections. "
                "Prefer standard-library functionality unless the user explicitly requests a dependency. "
                "Use clear names and sensible structure. "
                "For Python GUI/game requests include all imports, initialization, event bindings, and the correct main loop."
            )

            try:
                raw = await self._code_model_text(prompt, timeout=None)
            except CodeHelperError as exc:
                await emit("provider_timeout", provider=provider_name, model=model_name)
                answer = str(exc) + " Please try again or switch provider."
                return answer, DirectConversationReport(status=_CodeStatus(), success=False, final_message=answer)

            await emit("provider_responded", provider=provider_name, model=model_name)
            generated = code_service.strip_code_fences(raw)
            if not generated.strip():
                await emit("generation_rejected", reason="empty_source")
                answer = "The model returned empty source code, so no file was created."
                return answer, DirectConversationReport(status=_CodeStatus(), success=False, final_message=answer)

            valid, validation_error = code_service.validate_source(generated, language=language)
            repair_attempt = 0
            while not valid and repair_attempt < 2:
                repair_attempt += 1
                await emit("generation_repair", attempt=repair_attempt, language=language, error=validation_error[:800])
                repair_prompt = (
                    f"The following generated {language} single-file program failed syntax/compile validation. "
                    "Fix it and return the COMPLETE corrected raw source only. No Markdown fences or explanation.\n\n"
                    f"USER REQUEST:\n{current}\n\nVALIDATION ERROR:\n{validation_error}\n\nSOURCE:\n{generated}"
                )
                try:
                    repaired = code_service.strip_code_fences(
                        await self._code_model_text(repair_prompt, timeout=None)
                    )
                except CodeHelperError:
                    break
                if not repaired.strip():
                    break
                generated = repaired
                valid, validation_error = code_service.validate_source(generated, language=language)

            if not valid:
                await emit("generation_rejected", reason="validation_failed", error=validation_error[:1000])
                answer = (
                    "The model generated invalid code and Conduit could not repair it "
                    f"after {repair_attempt} attempt(s). No code file was saved.\n\n"
                    f"Validation error:\n{validation_error}"
                )
                return answer, DirectConversationReport(status=_CodeStatus(), success=False, final_message=answer)

            await emit("generation_validated", language=language)
            try:
                target = code_service.write_generated(
                    generated, language=language, prompt=current,
                    filename=intent.filename, path=intent.path,
                    base_dir=("" if intent.path else self._preferred_directory("code")),
                )
            except Exception as exc:
                answer = f"I couldn't generate the code file: {exc}"
                return answer, DirectConversationReport(status=_CodeStatus(), success=False, final_message=answer)

            await emit("generated", path=str(target), language=language)
            answer = f"Generated and validated {language} code and saved it to {target}."
            return answer, DirectConversationReport(status=_CodeStatus(), success=True, final_message=answer)

        if active is None:
            answer="Drop a code file into Conduit first."
            return answer, DirectConversationReport(status=_CodeStatus(),success=False,final_message=answer)

        source=code_service.read(active)
        language=code_service.detect_language(active)

        if intent.action in {"explain","review"}:
            await emit(intent.action, path=str(active), language=language)
            instruction = (
                "Explain this single code file clearly, including its purpose, important logic, and likely behavior."
                if intent.action=="explain" else
                "Review this single code file. Identify correctness issues, bugs, maintainability problems, security concerns, and concrete improvements."
            )
            answer=await self._code_model_text(
                f"{instruction}\n\nLANGUAGE: {language}\nFILE: {active.name}\n\nSOURCE:\n{source}"
            )
            return answer, DirectConversationReport(status=_CodeStatus(),success=True,final_message=answer)

        if intent.action in {"edit","optimize"}:
            await emit(intent.action, path=str(active), language=language)
            if intent.action=="optimize":
                task=("Optimize this code while preserving its externally visible behavior. Improve performance, clarity, and robustness where reasonable. ")
            else:
                task=("Modify the code exactly according to the user's request. You may rewrite the entire file when appropriate. ")
            prompt=(
                f"{task}Return ONLY the full replacement source code with no Markdown fences.\n\n"
                f"USER REQUEST:\n{current}\n\nLANGUAGE: {language}\nFILE: {active.name}\n\nCURRENT SOURCE:\n{source}"
            )
            revised=code_service.strip_code_fences(await self._code_model_text(prompt))
            if not revised.strip():
                answer="The model did not return revised source code."
                return answer, DirectConversationReport(status=_CodeStatus(),success=False,final_message=answer)
            try:
                target,backup=code_service.replace(revised,active,create_backup=True)
            except Exception as exc:
                answer=f"I couldn't edit the code file: {exc}"
                return answer, DirectConversationReport(status=_CodeStatus(),success=False,final_message=answer)
            await emit("edited", path=str(target), backup=str(backup or ""))
            verb="Optimized" if intent.action=="optimize" else "Updated"
            answer=f"{verb} {target.name}. A backup of the previous version was saved to {backup}."
            return answer, DirectConversationReport(status=_CodeStatus(),success=True,final_message=answer)

        if intent.action in {"run","test"}:
            await emit(intent.action, path=str(active), language=language)
            result=code_service.test(active) if intent.action=="test" else code_service.run(active)
            await emit("run_completed", success=result.success, category=result.category.value, exit_code=result.exit_code)
            pieces=[result.message]
            if result.stdout.strip(): pieces.append(f"Output:\n{result.stdout.strip()}")
            if result.stderr.strip(): pieces.append(f"Error output:\n{result.stderr.strip()}")
            if not result.success: pieces.append(f"Error category: {result.category.value}.")
            answer="\n\n".join(pieces)
            return answer, DirectConversationReport(status=_CodeStatus(),success=result.success,final_message=answer)

        if intent.action=="debug":
            await emit("debug_start", path=str(active), language=language)
            first=code_service.run(active)
            if first.success:
                answer="The code ran successfully, so I did not find a visible runtime or compilation error to repair."
                return answer, DirectConversationReport(status=_CodeStatus(),success=True,final_message=answer)
            if first.category.value=="runtime_missing":
                answer=f"I couldn't debug by execution because the required runtime/compiler is unavailable. {first.message}"
                return answer, DirectConversationReport(status=_CodeStatus(),success=False,final_message=answer)

            last=first; backup=None
            for attempt in range(1,4):
                await emit("repair_attempt", attempt=attempt, category=last.category.value)
                current_source=code_service.read(active)
                prompt=(
                    "Repair this SINGLE code file based on the execution failure below. Preserve intended behavior and make the smallest sound fix. "
                    "Return ONLY the full replacement source code with no Markdown fences.\n\n"
                    f"USER REQUEST:\n{current}\n\nLANGUAGE: {language}\nFILE: {active.name}\n"
                    f"ERROR CATEGORY: {last.category.value}\nSTDOUT:\n{last.stdout}\nSTDERR:\n{last.stderr}\n\nSOURCE:\n{current_source}"
                )
                revised=code_service.strip_code_fences(await self._code_model_text(prompt))
                if not revised.strip(): break
                target,new_backup=code_service.replace(revised,active,create_backup=(backup is None))
                if backup is None: backup=new_backup
                last=code_service.run(target)
                if last.success:
                    await emit("repair_succeeded", attempt=attempt, path=str(target))
                    answer=f"Fixed {target.name} and verified it runs successfully after {attempt} repair attempt(s)."
                    if last.stdout.strip(): answer += f"\n\nOutput:\n{last.stdout.strip()}"
                    if backup: answer += f"\n\nOriginal backup: {backup}"
                    return answer, DirectConversationReport(status=_CodeStatus(),success=True,final_message=answer)
            answer=(
                f"I couldn't fully repair {active.name} after up to 3 attempts. Last error category: {last.category.value}."
                + (f"\n\nError output:\n{last.stderr.strip()}" if last.stderr.strip() else "")
                + (f"\n\nOriginal backup: {backup}" if backup else "")
            )
            return answer, DirectConversationReport(status=_CodeStatus(),success=False,final_message=answer)

        if intent.action=="install_dependency":
            package=intent.package
            if not package:
                answer="Tell me the dependency/package name you want to install."
                return answer, DirectConversationReport(status=_CodeStatus(),success=False,final_message=answer)
            try:
                package=code_service.validate_package_name(package)
            except Exception as exc:
                answer=str(exc)
                return answer, DirectConversationReport(status=_CodeStatus(),success=False,final_message=answer)
            # Explicit confirmation before modifying the Python/npm environment.
            self._code_context["pending_install"]={"package":package,"language":language}
            answer=f"Install the {language} dependency '{package}'? Type YES to install or NO to cancel."
            return answer, DirectConversationReport(status=_CodeStatus(),success=False,final_message=answer)

        return None

    @classmethod
    def _could_be_file_processing_request(cls, message: str) -> bool:
        lowered = " ".join(message.casefold().split())
        active = file_service.get_active_file()

        has_dimensions = bool(re.search(r"(?i)\b\d{2,5}\s*[x×]\s*\d{2,5}\b", message))
        has_extension = bool(re.search(
            r"(?i)\.(?:pdf|docx?|txt|md|csv|xlsx?|json|xml|jpe?g|png|webp|bmp|gif|"
            r"mp3|wav|flac|m4a|mp4|mkv|mov|avi|webm|zip|tar|pptx?)\b", message
        ))
        file_words = (
            "file","pdf","image","photo","picture","pic","document","doc","docx",
            "spreadsheet","excel","csv","json","xml","audio","video","mp3","mp4",
            "archive","zip","presentation","ppt","pptx",
        )
        has_file_word = any(re.search(rf"(?i)\b{re.escape(w)}\b", lowered) for w in file_words)
        operation_words = (
            "summarize","summary","analyse","analyze","extract","extrach","ocr","resize",
            "compress","convert","change","make","turn","to word","word count","count words",
            "bullet","reformat","fix grammar","translate","statistics","filter","sort",
            "validate","transcribe","trim","unzip","describe","inspect","format",
        )
        has_operation = any(w in lowered for w in operation_words)
        active_reference = any(x in lowered for x in (
            "this file","that file","this image","this pic","this picture","this pdf",
            "this video","this audio","this document","this spreadsheet","this excel",
            "this json","this xml","this presentation","this ppt"," it ",
        ))

        if active is not None:
            kind = active.kind.value
            if re.search(
                r"(?i)\b(?:convert|change|turn|make|save)\b.*\b(?:to|into|as)\b.*"
                r"\b(?:pdf|docx|txt|csv|xlsx|json|png|jpg|jpeg|webp|mp3|wav)\b", message
            ):
                return True
            if kind == "spreadsheet" and re.search(
                r"(?i)\b(?:analy[sz]e|analysis|statistics?|stats?|sort|filter|inspect|validate|format)\b", message
            ):
                return True
            if kind in {"json","xml"} and re.search(
                r"(?i)\b(?:validate|format|analy[sz]e|analysis|inspect|convert)\b", message
            ):
                return True
            if kind == "presentation" and re.search(
                r"(?i)\b(?:summari[sz]e|summary|extract\s+text|analy[sz]e|analysis|inspect)\b", message
            ):
                return True
            if kind == "image" and re.search(
                r"(?i)\b(?:describe|ocr|read\s+(?:the\s+)?text|extract\s+text|inspect|metadata)\b", message
            ):
                return True
            if re.search(r"(?i)\bsummari[sz]e\b|\bsummary\b", message) and kind in {"document","text","pdf","presentation"}:
                return True
            if re.search(r"(?i)\b(?:word\s*count|count\s+words?|how\s+many\s+words)\b", message) and kind in {"document","text","code"}:
                return True
            if re.search(r"(?i)\b(?:bullet\s*points?|bullets?|convert\s+to\s+bullet\s*points?)\b", message) and kind in {"document","text"}:
                return True
            if kind == "image" and has_dimensions:
                return True
            if kind == "video" and re.search(r"(?i)\bmp3\b", message):
                return True
            if kind in {"video","audio"} and re.search(r"(?i)\btrim\b", message):
                return True
            if has_operation and (has_file_word or has_extension or active_reference):
                return True

        return has_operation and (has_file_word or has_extension or active_reference)


    def _ensure_file_context(self) -> dict[str, Any]:
        context = getattr(self, "_file_context", None)
        if context is None:
            context = {}
            self._file_context = context
        return context

    @staticmethod
    def _spreadsheet_column_from_text(text: str, columns: list[str]) -> str | None:
        for column in sorted(columns, key=len, reverse=True):
            if re.search(rf"(?i)(?<!\w){re.escape(column)}(?!\w)", text):
                return column
        stripped = text.strip().strip('"').strip("'")
        for column in columns:
            if stripped.casefold() == column.casefold():
                return column
        return None

    @staticmethod
    def _spreadsheet_sort_direction(text: str) -> bool:
        return not bool(re.search(r"(?i)\b(?:desc|descending|largest|highest|z\s*to\s*a)\b", text))

    @staticmethod
    def _spreadsheet_filter_from_text(text: str, columns: list[str]):
        column = ConversationSession._spreadsheet_column_from_text(text, columns)
        if not column:
            return None
        patterns = [
            (r"(?:>=|greater\s+than\s+or\s+equal(?:\s+to)?|at\s+least)\s*([^\s,]+)", "gte"),
            (r"(?:<=|less\s+than\s+or\s+equal(?:\s+to)?|at\s+most)\s*([^\s,]+)", "lte"),
            (r"(?:>|greater\s+than|above|over)\s*([^\s,]+)", "gt"),
            (r"(?:<|less\s+than|below|under)\s*([^\s,]+)", "lt"),
            (r"(?:!=|not\s+equal(?:\s+to)?)\s*([^\s,]+)", "ne"),
            (r"(?:=|equals?|equal\s+to|is)\s*([^\s,]+)", "eq"),
            (r"(?:contains?|including)\s+(.+)$", "contains"),
        ]
        for pattern, operator in patterns:
            match = re.search(pattern, text, flags=re.I)
            if not match:
                continue
            raw = match.group(1).strip().strip('"').strip("'")
            value: Any = raw
            if operator != "contains":
                try:
                    value = float(raw)
                    if value.is_integer():
                        value = int(value)
                except (TypeError, ValueError):
                    pass
            return {"column": column, "operator": operator, "value": value}
        return None

    async def _continue_pending_file_operation(self, message: str):
        context = self._ensure_file_context()
        pending = context.get("pending_operation")
        if not isinstance(pending, dict):
            return None
        active = file_service.get_active_file()
        if active is None or active.kind.value != "spreadsheet":
            context.pop("pending_operation", None)
            return None

        try:
            inspected = file_service.process(action="inspect", path=None, parameters={})
            columns = [str(x) for x in inspected.data.get("columns", [])]
        except Exception:
            context.pop("pending_operation", None)
            return None

        action = str(pending.get("action", ""))
        if action == "sort":
            column = self._spreadsheet_column_from_text(message, columns)
            if not column:
                return None
            context.pop("pending_operation", None)
            return await self._execute_file_plan(FilePlan(
                "sort", "", {"column": column, "ascending": self._spreadsheet_sort_direction(message)}
            ))
        if action == "filter":
            data = self._spreadsheet_filter_from_text(message, columns)
            if data is None:
                return None
            context.pop("pending_operation", None)
            return await self._execute_file_plan(FilePlan("filter", "", data))
        context.pop("pending_operation", None)
        return None

    async def _execute_file_plan(self, plan: FilePlan):
        try:
            result = file_service.process(
                action=plan.action, path=plan.path or None, parameters=plan.parameters
            )
        except (FileProcessingError, DependencyUnavailable) as exc:
            message = str(exc)
            return message, DirectConversationReport(
                status=_FileStatus(), success=False, final_message=message
            )
        except Exception as exc:
            message = f"File processing failed: {exc}"
            return message, DirectConversationReport(
                status=_FileStatus(), success=False, final_message=message
            )

        if result.semantic_instruction:
            try:
                generated = await self._complete_file_semantic_result(result)
                save_file = bool(plan.parameters.get("save_file", False))
                if result.action in {"summarize","analyze","describe"} and not save_file:
                    if result.action == "summarize":
                        generated = self._normalize_short_summary(generated)
                    return generated, DirectConversationReport(
                        status=_FileStatus(), success=True, final_message=generated
                    )
                result = file_service.complete_semantic(result, generated)
            except Exception as exc:
                message = f"I prepared the file, but the AI processing step failed: {exc}"
                return message, DirectConversationReport(
                    status=_FileStatus(), success=False, final_message=message
                )

        message = result.message
        if result.output_path:
            message += f" Saved output to {result.output_path}."

        if result.data.get("text") and plan.action in {"extract_text","ocr","transcribe"}:
            preview = str(result.data["text"]).strip()
            if preview:
                message += f"\n\n{preview[:5000]}"

        if plan.action == "statistics":
            message = (
                f"Spreadsheet has {result.data.get('rows')} row(s). "
                f"Numeric statistics: {result.data.get('statistics', {})}. "
                f"Missing values: {result.data.get('missing_values', {})}."
            )

        return message, DirectConversationReport(
            status=_FileStatus(), success=result.success, final_message=message
        )

    async def _execute_file_processing_request(self, current: str):
        active = file_service.get_active_file()
        lowered = " ".join(current.casefold().split())
        plan = None

        if active is not None:
            kind = active.kind.value

            if (
                "what can you do with this file" in lowered
                or "what can you do with this" in lowered
                or "file capabilities" in lowered
            ):
                try:
                    data = file_service.capabilities(None)
                except Exception as exc:
                    message = str(exc)
                    return message, DirectConversationReport(status=_FileStatus(), success=False, final_message=message)
                message = f"For this {data['file']['kind']} file I can: " + ", ".join(data["actions"]) + "."
                return message, DirectConversationReport(status=_FileStatus(), success=True, final_message=message)

            format_match = re.search(
                r"(?i)\b(?:convert|change|turn|make|save)\b.*\b(?:to|into|as)\b\s*"
                r"(pdf|docx|txt|csv|xlsx|json|png|jpg|jpeg|webp|mp3|wav)\b", current
            )
            if format_match:
                fmt = format_match.group(1).casefold()
                if kind == "pdf" and fmt in {"docx","word"}:
                    plan = FilePlan("to_word", "", {})
                elif kind == "video" and fmt in {"mp3","wav"}:
                    plan = FilePlan("extract_audio", "", {"format": fmt})
                elif kind in {"json","xml"} and fmt == "csv":
                    plan = FilePlan("convert_csv", "", {})
                else:
                    plan = FilePlan("convert", "", {"format": fmt})

            if plan is None and kind == "spreadsheet":
                try:
                    inspected = file_service.process(action="inspect", path=None, parameters={})
                    columns = [str(x) for x in inspected.data.get("columns", [])]
                except Exception:
                    columns = []

                if re.search(r"(?i)\b(?:analy[sz]e|analysis)\b", current):
                    plan = FilePlan("analyze", "", {})
                elif re.search(r"(?i)\b(?:statistics?|stats?)\b", current):
                    plan = FilePlan("statistics", "", {})
                elif re.search(r"(?i)\binspect\b", current):
                    plan = FilePlan("inspect", "", {})
                elif re.search(r"(?i)\bsort\b", current):
                    column = self._spreadsheet_column_from_text(current, columns)
                    if not column:
                        self._ensure_file_context()["pending_operation"] = {"action": "sort"}
                        available = ", ".join(columns) if columns else "the spreadsheet columns"
                        message = f"Which column would you like me to sort by? Available columns: {available}."
                        return message, DirectConversationReport(status=_FileStatus(), success=False, final_message=message)
                    plan = FilePlan("sort", "", {
                        "column": column,
                        "ascending": self._spreadsheet_sort_direction(current),
                    })
                elif re.search(r"(?i)\bfilter\b", current):
                    data = self._spreadsheet_filter_from_text(current, columns)
                    if data is None:
                        self._ensure_file_context()["pending_operation"] = {"action": "filter"}
                        available = ", ".join(columns) if columns else "the spreadsheet columns"
                        message = (
                            "What filter should I apply? For example: "
                            f"'Revenue greater than 220'. Available columns: {available}."
                        )
                        return message, DirectConversationReport(status=_FileStatus(), success=False, final_message=message)
                    plan = FilePlan("filter", "", data)
                elif re.search(r"(?i)\bvalidate\b", current):
                    message = (
                        "Validation isn't supported for spreadsheet files. "
                        "I can inspect, analyze, calculate statistics, filter, sort, or convert this spreadsheet."
                    )
                    return message, DirectConversationReport(status=_FileStatus(), success=False, final_message=message)
                elif re.search(r"(?i)\bformat\b", current):
                    message = (
                        "Formatting isn't supported as a standalone spreadsheet action. "
                        "I can inspect, analyze, calculate statistics, filter, sort, or convert this spreadsheet."
                    )
                    return message, DirectConversationReport(status=_FileStatus(), success=False, final_message=message)

            if plan is None and kind in {"json","xml"}:
                if re.search(r"(?i)\bvalidate\b", current):
                    plan = FilePlan("validate", "", {})
                elif re.search(r"(?i)\bformat\b", current):
                    plan = FilePlan("format", "", {})
                elif re.search(r"(?i)\b(?:analy[sz]e|analysis)\b", current):
                    plan = FilePlan("analyze", "", {})
                elif re.search(r"(?i)\binspect\b", current):
                    plan = FilePlan("inspect", "", {})
                elif re.search(r"(?i)\bconvert\b.*\bcsv\b|\bto\s+csv\b", current):
                    plan = FilePlan("convert_csv", "", {})

            if plan is None and kind == "presentation":
                if re.search(r"(?i)\bsummari[sz]e\b|\bsummary\b", current):
                    save_summary_file = bool(re.search(
                        r"(?i)\b(?:save|create|generate|make|write|export)\b.*\bsummary\b.*\b(?:file|txt|text)\b", current
                    ))
                    plan = FilePlan("summarize", "", {"save_file": save_summary_file})
                elif re.search(r"(?i)\bextract\s+text\b|\bread\s+(?:the\s+)?text\b", current):
                    plan = FilePlan("extract_text", "", {})
                elif re.search(r"(?i)\b(?:analy[sz]e|analysis)\b", current):
                    plan = FilePlan("analyze", "", {})
                elif re.search(r"(?i)\binspect\b", current):
                    plan = FilePlan("inspect", "", {})

            if plan is None and kind == "image":
                dims = re.search(r"(?i)\b(\d{2,5})\s*[x×]\s*(\d{2,5})\b", current)
                if dims:
                    plan = FilePlan("resize", "", {
                        "width": int(dims.group(1)),
                        "height": int(dims.group(2)),
                        "keep_aspect": False,
                    })
                elif re.search(r"(?i)\bdescribe\b", current):
                    plan = FilePlan("describe", "", {})
                elif re.search(r"(?i)\bocr\b|\bread\s+(?:the\s+)?text\b|\bextract\s+text\b", current):
                    plan = FilePlan("ocr", "", {})
                elif re.search(r"(?i)\binspect\b|\bmetadata\b", current):
                    plan = FilePlan("inspect", "", {})

            if plan is None and kind in {"document","text","pdf","presentation"}:
                summary_intent = bool(
                    re.search(r"(?i)\bsummari[sz]e\b|\bsummary\b", current)
                    or re.search(r"(?i)\bwhat(?:'s| is)\s+(?:written|in)\s+(?:this|it)\b", current)
                    or re.search(r"(?i)\btell me what(?:'s| is) written\b", current)
                    or re.search(r"(?i)\bwhat is (?:this|the) (?:doc|document|file) about\b", current)
                )
                if summary_intent:
                    save_summary_file = bool(
                        re.search(r"(?i)\b(?:save|create|generate|make|write|export)\b.*\bsummary\b.*\b(?:file|txt|text)\b", current)
                        or re.search(r"(?i)\bsummary\s+(?:file|txt|text)\b", current)
                        or re.search(r"(?i)\bsave\s+(?:the\s+)?summary\b", current)
                    )
                    plan = FilePlan("summarize", "", {"save_file": save_summary_file})
                elif kind in {"document","text"} and re.search(r"(?i)\b(?:word\s*count|count\s+words?|how\s+many\s+words)\b", current):
                    plan = FilePlan("word_count", "", {})
                elif kind in {"document","text"} and re.search(r"(?i)\b(?:bullet\s*points?|bullets?|convert\s+to\s+bullet\s*points?)\b", current):
                    plan = FilePlan("bullet_points", "", {})
                elif re.search(r"(?i)\bextract\s+text\b", current) and kind in {"pdf","presentation"}:
                    plan = FilePlan("extract_text", "", {})
                elif re.search(r"(?i)\b(?:analy[sz]e|analysis)\b", current):
                    plan = FilePlan("analyze", "", {})

            if plan is None and kind in {"video","audio"} and re.search(r"(?i)\btrim\b", current):
                times = re.findall(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", current)
                if len(times) >= 2:
                    plan = FilePlan("trim", "", {"start": times[0], "end": times[1]})
                elif len(times) == 1:
                    plan = FilePlan("trim", "", {"start": "0", "end": times[0]})

            if plan is None and kind == "video" and re.search(r"(?i)\bmp3\b", current):
                plan = FilePlan("extract_audio", "", {"format": "mp3"})

        if plan is None:
            router = AIFileRouter(self.agent.loop.provider, self.agent.loop.model)
            try:
                plan = await router.plan(current, active_file=str(active.path) if active else "")
            except Exception:
                return None
            if plan is None:
                return None

        return await self._execute_file_plan(plan)


    @staticmethod
    def _normalize_short_summary(text: str) -> str:
        """Keep normal file summaries as one concise chat paragraph."""
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if not clean:
            return clean

        words = clean.split()
        if len(words) > 30:
            clean = " ".join(words[:30]).rstrip(" ,;:-")
            if clean and clean[-1] not in ".!?":
                clean += "."
        return clean

    async def _complete_file_semantic_result(self, result) -> str:
        provider = self.agent.loop.provider
        model = self.agent.loop.model

        # Image description is a true vision request.
        if result.input_file.kind.value == "image" and result.action == "describe":
            response = await provider.describe_image(
                result.input_file.path,
                result.semantic_instruction,
                model=model,
            )
            return response.text.strip()

        text = result.semantic_text
        instruction = result.semantic_instruction
        if result.action == "summarize":
            instruction = (
                "Summarize the file in ONE clear paragraph of 20 to 30 words. "
                "Include only the most important information. Do not use bullets, "
                "headings, prefaces, or mention that you are summarizing."
            )
        if not text.strip():
            raise ValueError("No text content was available for semantic processing.")

        # Chunk long files so provider context limits do not make large documents
        # unusable. Each chunk is processed independently, then combined.
        chunk_size = 22000
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        outputs: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            prompt = (
                f"{instruction}\n\n"
                f"This is part {index} of {len(chunks)} of the same file. "
                "Do not invent content outside the supplied text.\n\n"
                f"FILE CONTENT:\n{chunk}"
            )
            response = await provider.specialist_chat(
                [ChatMessage(Role.USER, prompt)],
                model=model,
            )
            outputs.append(response.text.strip())

        if len(outputs) == 1:
            return outputs[0]

        if result.action in {"fix", "translate"}:
            return "\n\n".join(outputs)

        combine_prompt = (
            f"{instruction}\n\n"
            "Combine these partial results into one coherent final answer without "
            "adding facts that are not present. If this is a summary, the FINAL "
            "answer must still be one paragraph of 20 to 30 words.\n\n" +
            "\n\n".join(f"[Part {i}]\n{x}" for i, x in enumerate(outputs, start=1))
        )
        response = await provider.specialist_chat(
            [ChatMessage(Role.USER, combine_prompt)],
            model=model,
        )
        return response.text.strip()

    def register_gui_dropped_file(self, path: str, *, temporary: bool = False):
        """Future GUI hook: connect the drag/drop event directly to this method."""
        return file_service.register_dropped_file(path, temporary=temporary)

    @classmethod
    def _could_be_system_control_request(cls, message: str) -> bool:
        """Cheap semantic gate; exact interpretation is handled later."""
        lowered = " ".join(message.casefold().split())

        # File Explorer is an installed Windows shell application, not a request
        # to operate on a user file. Route it before the generic " file" guard.
        if re.search(
            r"(?i)\b(?:open|launch|start|show)\s+(?:the\s+)?(?:windows\s+)?file\s+explorer\b",
            message,
        ):
            return True

        concepts = (
            "wifi", "wi-fi", "wireless",
            "volume", "audio", "sound", "mute", "unmute", "louder", "quieter",
            "brightness", "brighter", "dimmer", "dim my screen", "dim the screen",
            "dark mode", "light mode", "dark theme", "light theme",
            "task manager", "windows settings", "system settings",
            "show desktop", "desktop view",
            "lock screen", "lock computer", "lock pc",
            "sleep display", "turn off display", "screen off",
            "snap window", "left half", "right half",
            "switch windows", "change window",
            "zoom in", "zoom out", "reset zoom",
            "browser tab", "closed tab", "next tab", "previous tab",
            "go back", "go forward", "reload page", "refresh page",
            "installed apps", "what apps are installed", "app status",
        )
        if any(x in lowered for x in concepts):
            return True

        # General app launch/close language can also be flexible:
        # "could you launch Spotify", "please quit Discord", etc.
        if re.search(r"(?i)\b(?:open|launch|start|run|close|quit|exit)\b", message):
            if any(word in lowered for word in (
                " folder", " file", " document", " path", " website", " site", " url"
            )):
                return False
            return True
        return False


    @staticmethod
    def _split_app_names(text: str) -> list[str]:
        parts = re.split(r"\s*(?:,|\band\b|&)\s*", text, flags=re.I)
        result = []
        for part in parts:
            value = re.sub(r"(?i)^\s*(?:the\s+)?(?:app|application)\s+", "", part).strip()
            value = re.sub(r"(?i)\s+(?:app|application)$", "", value).strip()
            if value:
                result.append(value)
        return result

    async def _execute_system_control_request(self, current: str):
        lowered = " ".join(current.casefold().split())

        async def run(tool_name: str, arguments: dict[str, Any] | None = None):
            result = await self.agent.tools.execute(
                ToolCall(tool_name, arguments or {}),
                confirmed=True,
            )
            success = bool(getattr(result, "success", False))
            message = str(getattr(result, "message", "")).strip()
            if not message:
                message = "System action completed." if success else "The system action failed."
            report = DirectConversationReport(
                status=_SystemStatus(),
                success=success,
                final_message=message,
            )
            return message, report

        # Audio.
        m = re.search(r"(?i)\bset\s+(?:the\s+)?volume\s+(?:to\s+)?(\d{1,3})\b", current)
        if m:
            return await run("system.volume_set", {"value": min(100, int(m.group(1)))})
        if "volume up" in lowered or "increase volume" in lowered or "raise volume" in lowered:
            amount = re.search(r"(?i)\b(?:by\s+)?(\d{1,3})\b", current)
            return await run("system.volume_up", {"step": int(amount.group(1)) if amount else 10})
        if "volume down" in lowered or "decrease volume" in lowered or "lower volume" in lowered:
            amount = re.search(r"(?i)\b(?:by\s+)?(\d{1,3})\b", current)
            return await run("system.volume_down", {"step": int(amount.group(1)) if amount else 10})
        if re.search(r"(?i)\bunmute\b", current):
            return await run("system.mute", {"muted": False})
        if re.search(r"(?i)\bmute\b", current):
            return await run("system.mute", {"muted": True})

        # Brightness.
        m = re.search(r"(?i)\bset\s+(?:the\s+)?brightness\s+(?:to\s+)?(\d{1,3})\b", current)
        if m:
            return await run("system.brightness_set", {"value": min(100, int(m.group(1)))})
        if "brightness up" in lowered or "increase brightness" in lowered:
            amount = re.search(r"(?i)\b(?:by\s+)?(\d{1,3})\b", current)
            return await run("system.brightness_up", {"step": int(amount.group(1)) if amount else 10})
        if "brightness down" in lowered or "decrease brightness" in lowered:
            amount = re.search(r"(?i)\b(?:by\s+)?(\d{1,3})\b", current)
            return await run("system.brightness_down", {"step": int(amount.group(1)) if amount else 10})

        # Wi-Fi and theme.
        if "wifi status" in lowered or "wi-fi status" in lowered:
            return await run("system.wifi_status")

        # Canonical instant forms:
        #   turn on wifi
        #   wifi on
        #   turn wifi on
        if re.search(r"(?i)\b(?:turn\s+on\s+wi-?fi|wi-?fi\s+on|turn\s+wi-?fi\s+on)\b", current):
            return await run("system.wifi_toggle", {"enabled": True})
        if re.search(r"(?i)\b(?:turn\s+off\s+wi-?fi|wi-?fi\s+off|turn\s+wi-?fi\s+off)\b", current):
            return await run("system.wifi_toggle", {"enabled": False})
        if "toggle wifi" in lowered or "toggle wi-fi" in lowered:
            return await run("system.wifi_toggle", {})
        if "dark mode" in lowered:
            if any(x in lowered for x in ("off", "disable", "light mode")):
                return await run("system.dark_mode", {"enabled": False})
            return await run("system.dark_mode", {"enabled": True})

        # Windows shell controls.
        if re.search(
            r"(?i)\b(?:open|launch|start|show)\s+(?:the\s+)?(?:windows\s+)?file\s+explorer\b",
            current,
        ):
            return await run("system.open_app", {"app": "file explorer"})
        if "open task manager" in lowered:
            return await run("system.open_task_manager")
        if "open system settings" in lowered or "open windows settings" in lowered:
            return await run("system.open_settings", {})
        if "show desktop" in lowered:
            return await run("system.show_desktop")
        if "lock screen" in lowered or "lock computer" in lowered or lowered == "lock pc":
            return await run("system.lock")
        if "sleep display" in lowered or "turn off display" in lowered:
            return await run("system.sleep_display")
        if "snap window left" in lowered or "snap the window left" in lowered:
            return await run("system.snap_window", {"direction": "left"})
        if "snap window right" in lowered or "snap the window right" in lowered:
            return await run("system.snap_window", {"direction": "right"})
        if "switch windows" in lowered:
            return await run("system.switch_windows")

        # Focused-browser/page shortcuts. Existing structured browser commands still
        # take precedence earlier in the conversation router.
        if "zoom in" in lowered:
            return await run("system.browser_zoom", {"action": "in"})
        if "zoom out" in lowered:
            return await run("system.browser_zoom", {"action": "out"})
        if "reset zoom" in lowered:
            return await run("system.browser_zoom", {"action": "reset"})
        if "reopen closed tab" in lowered:
            return await run("system.browser_tab_shortcut", {"action": "reopen"})
        if "next browser tab" in lowered:
            return await run("system.browser_tab_shortcut", {"action": "next"})
        if "previous browser tab" in lowered:
            return await run("system.browser_tab_shortcut", {"action": "previous"})

        # General installed-app opening/closing, including multi-app commands.
        m = re.match(r"(?i)^\s*(?:open|launch|start)\s+(.+?)\s*$", current)
        if m:
            apps = self._split_app_names(m.group(1))
            if len(apps) > 1:
                return await run("system.open_apps", {"apps": apps})
            if apps:
                return await run("system.open_app", {"app": apps[0]})

        m = re.match(r"(?i)^\s*(?:close|quit|exit)\s+(.+?)\s*$", current)
        if m:
            apps = self._split_app_names(m.group(1))
            if len(apps) > 1:
                return await run("system.close_apps", {"apps": apps})
            if apps:
                return await run("system.close_app", {"app": apps[0]})

        return None

    async def _make_system_plan(
        self,
        current: str,
        *,
        needs_history: bool,
    ) -> SystemPlan | None:
        context = ""
        if needs_history:
            context = "\n".join(
                f"User: {turn.user}\nConduit: {turn.assistant}"
                for turn in self.session_memory.recent_turns(2)
            )
        router = AISystemRouter(
            self.agent.loop.provider,
            self.agent.loop.model,
        )
        try:
            return await router.plan(current, recent_context=context)
        except Exception:
            # Fail closed: never guess a system side effect.
            return None

    async def _execute_system_plan(self, plan: SystemPlan):
        result = await self.agent.tools.execute(
            ToolCall(plan.action, dict(plan.arguments)),
            confirmed=True,
        )
        success = bool(getattr(result, "success", False))
        message = str(getattr(result, "message", "")).strip()
        if not message:
            message = "System action completed." if success else "The system action failed."
        return message, DirectConversationReport(
            status=_SystemStatus(),
            success=success,
            final_message=message,
        )

    @staticmethod
    def _browser_name_from_text(message: str) -> str:
        lowered = " ".join(message.casefold().split())
        aliases = (
            ("opera gx", ("opera gx", "operagx")),
            ("chrome", ("chrome", "google chrome")),
            ("edge", ("edge", "microsoft edge")),
            ("firefox", ("firefox", "mozilla firefox")),
            ("opera", ("opera",)),
            ("brave", ("brave",)),
            ("vivaldi", ("vivaldi",)),
            ("safari", ("safari",)),
        )
        for canonical, names in aliases:
            if any(re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", lowered) for name in names):
                return canonical
        return ""

    @classmethod
    def _could_be_browser_control_request(cls, message: str) -> bool:
        lowered = " ".join(message.casefold().split())
        browser_name = cls._browser_name_from_text(message)

        explicit_browser_context = (
            browser_name
            or "my browser" in lowered
            or "default browser" in lowered
            or "browser session" in lowered
            or "browser sessions" in lowered
            or "browser tab" in lowered
            or "browser tabs" in lowered
            or "incognito" in lowered
            or "private mode" in lowered
            or "private window" in lowered
        )
        management = any(phrase in lowered for phrase in (
            "what browsers are installed",
            "which browsers are installed",
            "browsers installed",
            "installed browsers",
            "which one is my default browser",
            "what is my default browser",
            "list browser sessions",
            "list my browser sessions",
            "switch browser session",
            "switch to browser session",
            "list tabs",
            "list my tabs",
            "list browser tabs",
            "switch tab",
            "switch to tab",
            "close tab",
            "close all tabs",
            "new tab",
            "open a new tab",
            "attach to my existing",
            "attach to existing",
            "attach existing",
            "go back",
            "go forward",
            "reload",
            "refresh",
            "browser screenshot",
            "screenshot of the browser",
        ))
        if management:
            return True

        if browser_name and re.search(
            r"(?i)\b(?:switch(?:\s+to)?|open|close)\b.*\btab\b",
            message,
        ):
            return True
        if re.search(
            r"(?i)^\s*close\s+.+?\s+tab\s*$",
            message,
        ):
            return True
        if re.search(
            r"(?i)^\s*switch(?:\s+to)?\s+.+?\s+tab\s*$",
            message,
        ):
            return True

        if explicit_browser_context and any(
            token in lowered.split()
            for token in ("open", "search", "find", "browse", "go", "launch")
        ):
            return True

        # A simple visible site-open request implicitly means the user's default
        # real browser even when the word "browser" is omitted:
        #   open youtube
        #   open reddit
        #   open github
        # But "open youtube and play the latest episode..." is NOT a simple site
        # open because the whole remainder is not a known site/URL; that continues
        # to the dedicated YouTube content agent.
        if re.match(
            r"(?i)^\s*(?:please\s+)?(?:open|launch|go\s+to|browse\s+to)\b",
            message,
        ):
            subject = cls._browser_open_subject(message)
            if subject and cls._known_site_url(subject):
                return True

        # Explicit browser searches are caught above. Content-specific YouTube
        # commands remain available to the dedicated YouTube agent.
        return False

    @staticmethod
    def _browser_display_name(name: str) -> str:
        value = (name or "").strip().casefold()
        if value == "opera gx":
            return "Opera GX"
        if value == "chrome":
            return "Chrome"
        if value == "edge":
            return "Edge"
        if value == "firefox":
            return "Firefox"
        if value == "opera":
            return "Opera"
        if value == "brave":
            return "Brave"
        if value == "vivaldi":
            return "Vivaldi"
        if value == "safari":
            return "Safari"
        return name.strip().title()

    @staticmethod
    def _browser_private_requested(message: str) -> bool:
        lowered = message.casefold()
        return any(term in lowered for term in (
            "incognito", "private mode", "private window", "inprivate",
        ))

    @staticmethod
    def _known_site_url(subject: str) -> str:
        value = " ".join(subject.casefold().split()).strip(" .?!")
        aliases = {
            "youtube": "https://www.youtube.com",
            "gmail": "https://mail.google.com",
            "google": "https://www.google.com",
            "google drive": "https://drive.google.com",
            "drive": "https://drive.google.com",
            "facebook": "https://www.facebook.com",
            "instagram": "https://www.instagram.com",
            "reddit": "https://www.reddit.com",
            "amazon": "https://www.amazon.com",
            "github": "https://github.com",
            "chatgpt": "https://chatgpt.com",
            "whatsapp web": "https://web.whatsapp.com",
            "whatsapp": "https://web.whatsapp.com",
        }
        if value in aliases:
            return aliases[value]
        if re.match(r"^https?://", subject.strip(), re.I):
            return subject.strip()
        if re.match(r"^[a-z0-9.-]+\.[a-z]{2,}(?:/.*)?$", subject.strip(), re.I):
            return "https://" + subject.strip()
        return ""

    @classmethod
    def _browser_open_subject(cls, message: str) -> str:
        text = message.strip()
        # Remove opening verb.
        text = re.sub(
            r"(?i)^\s*(?:please\s+)?(?:open|launch|go\s+to|browse\s+to)\s+",
            "",
            text,
        ).strip()

        # Private/incognito is a browser modifier, never part of the site/query.
        # Remove it BEFORE stripping the trailing browser clause so a command
        # like "open youtube in chrome incognito" becomes simply "youtube".
        text = re.sub(
            r"(?i)\s+(?:in\s+)?(?:incognito|inprivate|private(?:\s+mode|\s+window)?)\s*$",
            "",
            text,
        ).strip()

        # Remove browser placement clauses.
        text = re.sub(
            r"(?i)\s+(?:in|using|with)\s+(?:my\s+|the\s+)?(?:default\s+)?browser\s*$",
            "",
            text,
        ).strip()
        for name in ("opera gx", "google chrome", "microsoft edge", "chrome", "edge",
                     "firefox", "opera", "brave", "vivaldi", "safari"):
            text = re.sub(
                rf"(?i)\s+(?:in|using|with)\s+{re.escape(name)}\s*$",
                "",
                text,
            ).strip()
        return text

    @classmethod
    def _browser_search_query(cls, message: str) -> str:
        text = message.strip()
        text = re.sub(r"(?i)^\s*(?:please\s+)?(?:search(?:\s+for)?|find|look\s+up)\s+", "", text).strip()
        text = re.sub(
            r"(?i)\s+(?:in|using|with)\s+(?:my\s+|the\s+)?(?:default\s+)?browser\s*$",
            "",
            text,
        ).strip()
        for name in ("opera gx", "google chrome", "microsoft edge", "chrome", "edge",
                     "firefox", "opera", "brave", "vivaldi", "safari"):
            text = re.sub(rf"(?i)\s+(?:in|using|with)\s+{re.escape(name)}\s*$", "", text).strip()
        return text

    async def _execute_browser_control_request(
        self,
        current: str,
    ) -> tuple[str, DirectConversationReport] | None:
        import urllib.parse

        lowered = " ".join(current.casefold().split())
        browser_name = self._browser_name_from_text(current)
        private = self._browser_private_requested(current)
        browser = self.agent.browser

        def report(answer: str) -> tuple[str, DirectConversationReport]:
            return answer, DirectConversationReport(
                status=_BrowserStatus(),
                final_message=answer,
            )

        # Browser discovery must return the browser engine's deterministic result
        # directly; it is not a web-research question.
        if any(phrase in lowered for phrase in (
            "what browsers are installed",
            "which browsers are installed",
            "browsers installed",
            "installed browsers",
            "which one is my default browser",
            "what is my default browser",
        )):
            result = await browser.installed()
            data = dict(result.data)
            installed = list(data.get("browsers") or [])
            default_name = str(data.get("default_browser") or "")
            if installed:
                names = ", ".join(
                    self._browser_display_name(str(item.get("name", "")))
                    for item in installed
                )
                if default_name:
                    return report(
                        f"Installed supported browsers: {names}. "
                        f"Your default browser is {self._browser_display_name(default_name)}."
                    )
                return report(f"Installed supported browsers: {names}. I couldn't identify the default browser.")
            return report("I couldn't detect any supported installed browsers.")

        if "list" in lowered and "session" in lowered:
            result = await browser.list_sessions()
            sessions = list(result.data.get("sessions") or [])
            if not sessions:
                return report("There are no active Conduit browser sessions.")
            parts = []
            for item in sessions:
                marker = " (active)" if item.get("active") else ""
                parts.append(
                    f"{item.get('session_id')}: {self._browser_display_name(str(item.get('browser', '')))} "
                    f"[{item.get('mode')}/{item.get('transport')}]{marker}"
                )
            return report("Browser sessions: " + "; ".join(parts) + ".")

        switch_session = re.search(
            r"(?i)\bswitch(?:\s+to)?\s+(?:browser\s+)?session\s+([a-z0-9_-]+)",
            current,
        )
        if switch_session:
            result = await browser.switch_session(switch_session.group(1))
            return report(result.message)

        attach_match = re.search(
            r"(?i)\battach(?:\s+to)?\s+(?:my\s+)?(?:existing\s+)?"
            r"(?:chrome|google chrome|edge|microsoft edge|opera gx|opera|brave|vivaldi|firefox)"
            r"(?:\s+browser)?\b",
            current,
        )
        if attach_match:
            if not browser_name:
                return report("Please name the browser you want me to attach to.")
            result = await browser.attach_existing(browser_name)
            return report(result.message)

        if (
            "list tabs" in lowered
            or "list my tabs" in lowered
            or "list browser tabs" in lowered
        ):
            await browser.ensure_native_browser_session(browser=browser_name)
            result = await browser.list_tabs()
            tabs = list(result.data.get("tabs") or [])
            if not tabs:
                return report(result.message)
            rendered = "; ".join(
                f"{item.get('index')}: {item.get('title') or item.get('url') or 'Untitled'}"
                + (" (active)" if item.get("active") else "")
                for item in tabs
            )
            return report(f"Tabs: {rendered}.")

        qualified_tab = re.search(
            r"(?i)\b(?:switch(?:\s+to)?|open)\s+(?:the\s+)?"
            r"(?:chrome|google chrome|edge|microsoft edge|opera gx|opera|firefox|brave|vivaldi|safari)"
            r"(?:\s+browser)?\s+tab\s+(.+?)\s*$",
            current,
        )
        if qualified_tab and browser_name:
            await browser.ensure_native_browser_session(browser=browser_name)
            value = qualified_tab.group(1).strip()
            tab: int | str = int(value) if value.isdigit() else value
            result = await browser.switch_tab(tab)
            return report(result.message)

        reversed_title_tab = re.search(
            r"(?i)^\s*switch(?:\s+to)?\s+(.+?)\s+tab\s*$",
            current,
        )
        if reversed_title_tab:
            value = reversed_title_tab.group(1).strip()
            if value.casefold() not in {
                "browser", "chrome", "google chrome", "edge", "microsoft edge",
                "opera", "opera gx", "firefox", "brave", "vivaldi", "safari",
            }:
                await browser.ensure_native_browser_session(browser=browser_name)
                tab: int | str = int(value) if value.isdigit() else value
                result = await browser.switch_tab(tab)
                return report(result.message)

        switch_tab = re.search(
            r"(?i)\b(?:switch(?:\s+to)?|open)\s+(?:the\s+)?tab\s+(.+?)\s*$",
            current,
        )
        if switch_tab:
            await browser.ensure_native_browser_session(browser=browser_name)
            value = switch_tab.group(1).strip()
            tab: int | str = int(value) if value.isdigit() else value
            result = await browser.switch_tab(tab)
            return report(result.message)

        if "new tab" in lowered or "open a new tab" in lowered:
            current_requested = bool(re.search(
                r"(?i)\b(?:current|active)\s+browser\b",
                current,
            ))

            if current_requested and not browser_name:
                result = await browser.new_tab()
            else:
                # Simple rule: focus the requested/default existing browser and
                # press Ctrl+T. No launch, URL handoff, resize or maximize.
                result = await browser.new_tab_focus_only(
                    browser=browser_name,
                )
            return report(result.message)

        if "close all tabs" in lowered:
            await browser.ensure_native_browser_session(browser=browser_name)
            result = await browser.close_all_tabs()
            return report(result.message)

        reversed_close_tab = re.search(
            r"(?i)^\s*close\s+(.+?)\s+tab\s*$",
            current,
        )
        if reversed_close_tab:
            value=reversed_close_tab.group(1).strip()
            if value.casefold() not in {"all","browser","chrome","google chrome","edge","microsoft edge",
                                        "opera","opera gx","firefox","brave","vivaldi","safari"}:
                await browser.ensure_native_browser_session(browser=browser_name)
                tab: int | str=int(value) if value.isdigit() else value
                result=await browser.close_tab(tab)
                return report(result.message)

        close_tab = re.search(
            r"(?i)\bclose\s+(?:the\s+)?tab(?:\s+(.+?))?\s*$",
            current,
        )
        if close_tab:
            await browser.ensure_native_browser_session(browser=browser_name)
            raw = (close_tab.group(1) or "").strip()
            tab: int | str | None = None
            if raw:
                tab = int(raw) if raw.isdigit() else raw
            result = await browser.close_tab(tab)
            return report(result.message)

        if re.search(r"(?i)\b(?:go\s+)?back\b", current):
            result = await browser.back()
            return report(result.message)

        if re.search(r"(?i)\b(?:go\s+)?forward\b", current):
            result = await browser.forward()
            return report(result.message)

        if "reload" in lowered or "refresh" in lowered:
            result = await browser.reload()
            return report(result.message)

        if "screenshot" in lowered and "browser" in lowered:
            result = await browser.screenshot()
            return report(result.message)

        # Explicit browser search is a visible real-profile task, not web.search.
        if re.match(r"(?i)^\s*(?:please\s+)?(?:search(?:\s+for)?|find|look\s+up)\b", current):
            query = self._browser_search_query(current)
            if not query:
                return None
            url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
            result = await browser.use_default_profile(
                browser=browser_name,
                url=url,
                private=private,
            )
            chosen = self._browser_display_name(
                str(result.data.get("browser") or browser_name or "default browser")
            )
            return report(f"I searched for {query} in {chosen}.")

        # "open X in my/default/named browser" uses the user's real profile.
        if re.match(r"(?i)^\s*(?:please\s+)?(?:open|launch|go\s+to|browse\s+to)\b", current):
            subject = self._browser_open_subject(current)
            url = self._known_site_url(subject)
            if not url:
                # If it is not a known URL/site, treat "open X" as a visible
                # browser search rather than inventing a domain.
                url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(subject)
            result = await browser.use_default_profile(
                browser=browser_name,
                url=url,
                private=private,
            )
            chosen = self._browser_display_name(
                str(result.data.get("browser") or browser_name or "default browser")
            )
            return report(f"I opened {subject} in {chosen}.")

        return None

    def _could_be_messaging_request(self, message: str) -> bool:
        """Detect messaging intent independent of exact word order.

        Examples that must all route here:
          open whatsapp chat with basit
          open chat with basit on whatsapp
          message basit on whatsapp
          send basit hi on telegram
        """
        lowered = " ".join(message.casefold().split())
        tokens = set(lowered.replace("/", " ").replace("-", " ").split())

        service_named = any(name in tokens or name in lowered for name in ("whatsapp", "telegram", "discord"))
        has_open = "open" in tokens
        has_chat = "chat" in tokens or "conversation" in tokens
        has_with = "with" in tokens
        has_send = any(word in tokens for word in ("send", "message", "msg", "text", "tell"))
        has_read = (
            "read" in tokens
            or "recent" in tokens
            or "latest message" in lowered
            or "last message" in lowered
            or "what did" in lowered
        )

        if service_named and ((has_open and (has_chat or has_with)) or has_send or has_read):
            return True

        # Follow-up messaging turns can omit service and recipient.
        active_service = self._messaging_context.get("service", "")
        if not active_service:
            return False

        followup = (
            lowered.startswith("try ")
            or lowered in {"try again", "again", "send it", "open it"}
            or has_send
            or has_read
            or (has_open and has_chat)
        )
        return followup

    @staticmethod
    def _inline_messaging_send(current: str) -> tuple[str, str] | None:
        """Extract only clearly literal combined open-chat + message requests.

        If the user asks Conduit to write/rewrite/style the message, return None
        so the AI messaging brain gets the full instruction.
        """
        import re

        text = current.strip()
        match = re.search(
            r"(?ix)\b(?:and\s+)?(?:message|text|send|say)\s+(?:him\s+|her\s+|them\s+)?(?:\"([^\"]+)\"|'([^']+)'|(.+?))\s*$",
            text,
        )
        if not match:
            return None

        message = next((g for g in match.groups() if g is not None), "").strip()
        if not message:
            return None

        lowered = message.casefold()
        # Any writing/style intent must go through the AI composer. Keep this
        # broad so requests such as "make it professional/funny/friendly",
        # "write it like an application/email/letter", "polite/formal/casual",
        # etc. are not flattened into literal dictated text.
        composition_markers = (
            "make it ", "make this ", "rewrite", "rephrase", "improve",
            "professional", "formal", "polite", "respectful", "friendly",
            "funny", "humorous", "casual", "apologetic", "convincing",
            "persuasive", "application", "email", "e-mail", "mail type",
            "letter", "paragraph", "proper message", "well written",
            "well-written", "draft", "compose", "write it", "word it",
            "tell him", "tell her", "tell them",
        )
        if any(marker in lowered for marker in composition_markers):
            return None

        prefix = text[: match.start()].strip()
        recipient = ""
        recipient_match = re.search(
            r"(?ix)\b(?:chat\s+(?:with|of)|with)\s+(.+?)(?=\s+(?:in|on)\s+(?:whatsapp|telegram|discord)\b|\s+and\b|$)",
            prefix,
        )
        if recipient_match:
            recipient = recipient_match.group(1).strip()

        return recipient, message

    async def _make_messaging_plan(self, current: str, *, needs_history: bool) -> MessagingPlan | None:
        router = AIMessagingRouter(self.agent.loop.provider, model=self.agent.loop.model)
        context_lines = []
        history = self._history_text() if (needs_history or self._messaging_context) else ""
        if history:
            context_lines.append(history)
        if self._messaging_context:
            context_lines.append(
                "ACTIVE MESSAGING CONTEXT: "
                + json.dumps(self._messaging_context, ensure_ascii=False)
            )
        context = "\n".join(context_lines)

        # Deterministic combined request: "open the chat of Maryam in WhatsApp
        # and message Hi" is a SEND task even if a small model misclassifies it.
        lowered = current.casefold().strip()
        inline_send = self._inline_messaging_send(current)
        if inline_send is not None:
            recipient_hint, exact_message = inline_send
            service = (
                "whatsapp" if "whatsapp" in lowered
                else ("telegram" if "telegram" in lowered
                      else ("discord" if "discord" in lowered
                            else self._messaging_context.get("service", "")))
            )
            if service:
                return MessagingPlan(
                    "messaging.send",
                    service,
                    recipient=recipient_hint or self._messaging_context.get("recipient", ""),
                    message=exact_message,
                )

        # Deterministic correction follow-up: after a failed recipient lookup,
        # "try NAME" means retry the same messaging action/service with NAME.
        if self._messaging_context.get("service") and lowered.startswith("try "):
            recipient = current[4:].strip()
            if recipient:
                return MessagingPlan(
                    self._messaging_context.get("last_action", "messaging.open_chat"),
                    self._messaging_context["service"],
                    recipient=recipient,
                )

        try:
            plan = await router.plan(current, history=context)
            if plan is not None:
                inline_send = self._inline_messaging_send(current)
                if inline_send is not None and plan.action != "messaging.send":
                    recipient_hint, exact_message = inline_send
                    plan = MessagingPlan(
                        "messaging.send",
                        plan.service,
                        recipient=plan.recipient or recipient_hint,
                        message=exact_message,
                    )
                return plan
        except Exception:
            pass
        return self._fallback_messaging_plan(
            current,
            service_hint=self._messaging_context.get("service", ""),
            action_hint=self._messaging_context.get("last_action", ""),
        )

    @staticmethod
    def _fallback_messaging_plan(
        current: str,
        *,
        service_hint: str = "",
        action_hint: str = "",
    ) -> MessagingPlan | None:
        import re
        lowered = current.casefold()
        service = (
            "whatsapp" if "whatsapp" in lowered
            else ("telegram" if "telegram" in lowered
                  else ("discord" if "discord" in lowered else service_hint))
        )
        if not service:
            return None

        if lowered.strip().startswith("try "):
            recipient = current.strip()[4:].strip()
            return MessagingPlan(
                action_hint or "messaging.open_chat",
                service,
                recipient=recipient,
            )

        if any(term in lowered for term in ("read recent", "latest message", "last message", "what did")):
            match = re.search(r"(?:from|with)\s+(.+?)(?:\s+on\s+(?:whatsapp|telegram|discord)|$)", current, re.I)
            return MessagingPlan("messaging.read_recent", service, recipient=(match.group(1).strip() if match else ""))

        if "open" in lowered and "chat" in lowered:
            match = re.search(r"(?:chat\s+(?:with|of)|with)\s+(.+?)(?:\s+on\s+(?:whatsapp|telegram|discord)|$)", current, re.I)
            return MessagingPlan("messaging.open_chat", service, recipient=(match.group(1).strip() if match else ""))

        # Follow-up send with an already-resolved recipient can omit the service/name.
        return MessagingPlan(
            "messaging.send",
            service,
            recipient="",
            compose_instruction=current,
        )

    async def _compose_messaging_text(self, user_message: str, plan: MessagingPlan) -> str:
        if plan.message:
            return plan.message

        # The current user's wording is the factual source of truth. The router's
        # compose_instruction is only a style/intent hint and may itself be imperfect.
        # Never let a router paraphrase become the authority for message facts.
        original_request = user_message.strip()
        composition_hint = (plan.compose_instruction or "").strip()
        writer_prompt = (
            "You are Conduit's message-writing brain. Draft ONLY the final message "
            "that may be sent after user approval.\n\n"
            "STRICT RULES:\n"
            "- Use ONLY facts explicitly stated by the user. Do not infer the type of "
            "event, meeting, class, work shift, appointment, relationship, reason, "
            "schedule, rescheduling need, assistance offer, or any other circumstance.\n"
            "- NEVER use placeholders such as [Name], [Recipient's Name], [Your Name], "
            "Dear [Name], or similar.\n"
            "- Do NOT add a greeting/salutation or sender sign-off by default. No "
            "'Dear ...', 'Best regards', 'Sincerely', or sender name unless the user "
            "explicitly asks for those things.\n"
            "- For WhatsApp/Telegram/Discord, default to ONE concise natural paragraph. Use up "
            "to three short paragraphs only when genuinely needed for readability.\n"
            "- When professional/formal is requested, make the wording genuinely polished, "
            "considerate, and natural rather than merely correcting grammar. Safe conversational "
            "framing such as 'I wanted to let you know...' and neutral courtesy such as "
            "'Thank you for understanding.' are allowed because they do not invent an external fact. "
            "Do not turn it into a formal letter unless requested.\n"
            "- When friendly/casual is requested, make it natural and warm.\n"
            "- When funny/humorous is requested, make it light and playful without "
            "changing the facts.\n"
            "- When application/request, email/mail, or letter style is explicitly requested, use that "
            "format, but still do not invent names or facts.\n"
            "- Preserve the user's intended meaning. Never add facts merely to make the "
            "message sound complete.\n"
            "- Treat ORIGINAL USER REQUEST below as the ONLY factual authority. The "
            "ROUTER COMPOSITION HINT may help with tone/intent, but it may be inaccurate; "
            "NEVER copy a fact from that hint unless the same fact is supported by the "
            "original request.\n"
            "- Output ONLY the message text. No explanation, label, quotation marks, "
            "recipient name, sender name, or approval language.\n\n"
            f"ORIGINAL USER REQUEST:\n{original_request}\n\n"
            f"ROUTER COMPOSITION HINT (NON-AUTHORITATIVE):\n{composition_hint or '(none)'}"
        )
        specialist = getattr(
            self.agent.loop.provider,
            "specialist_chat",
            self.agent.loop.provider.chat,
        )
        drafted = await specialist(
            [ChatMessage(Role.USER, writer_prompt)],
            model=self.agent.loop.model,
        )
        candidate = drafted.text.strip().strip('"').strip()

        # Second pass is a factuality/style audit. This is intentionally separate
        # from the first generation so unsupported details such as "meeting",
        # "reschedule", or invented placeholders are removed before approval.
        audit_prompt = (
            "You are Conduit's outgoing-message safety editor. Compare the draft "
            "against the ORIGINAL USER INSTRUCTION below and return a corrected final "
            "message ONLY.\n\n"
            "Remove EVERY factual detail that the user did not explicitly provide. "
            "Examples of unsupported additions to remove include meetings, appointments, "
            "classes, work shifts, plans, rescheduling, assistance offers, medical "
            "details, dates beyond those stated, promises, and relationships.\n"
            "Remove all recipient/sender placeholders and unnecessary salutations or "
            "sign-offs, including Dear [Name], [Recipient's Name], Best regards, "
            "Sincerely, and [Your Name].\n"
            "Keep AND actively preserve the requested tone/style. If professional/formal wording "
            "was requested and the draft is blunt, robotic, or just repeats the user's raw wording, "
            "rewrite it into a polished, considerate, natural professional message while keeping the "
            "same facts. Safe non-factual courtesy/framing is explicitly allowed, for example "
            "'I wanted to let you know that...' or 'Thank you for understanding.' These phrases do "
            "not count as invented circumstances. For ordinary WhatsApp/Telegram/Discord messages, "
            "prefer one concise natural paragraph and no formal letter greeting/sign-off unless "
            "explicitly requested. Do not weaken or change facts the user actually gave.\n"
            "Output ONLY the corrected message text.\n\n"
            "IMPORTANT: The ORIGINAL USER REQUEST is the sole source of factual truth. "
            "Do not treat any router/composer paraphrase as evidence for a fact.\n\n"
            f"ORIGINAL USER REQUEST:\n{original_request}\n\n"
            f"DRAFT TO AUDIT:\n{candidate}"
        )
        audited = await specialist(
            [ChatMessage(Role.USER, audit_prompt)],
            model=self.agent.loop.model,
        )
        final_text = audited.text.strip().strip('"').strip()

        # A specialist/auditor must never leak its own task commentary into an
        # outgoing message. Small local models can occasionally answer the audit
        # instruction itself ("no draft provided", "cannot audit", etc.) instead
        # of returning message text. Detect those meta-responses and recover with
        # one lean finalization call that contains the original request AND the
        # concrete draft again. If recovery is still meta/empty, fall back to the
        # first factual draft rather than ever offering audit chatter for sending.
        def _looks_like_audit_meta(text: str) -> bool:
            lowered = (text or "").casefold()
            markers = (
                "cannot proceed with the audit",
                "can't proceed with the audit",
                "no draft message",
                "draft message provided",
                "provide the draft",
                "review against the original",
                "original user instruction",
                "draft to audit",
                "as an auditor",
                "safety editor",
            )
            return (not text.strip()) or any(marker in lowered for marker in markers)

        if _looks_like_audit_meta(final_text):
            recovery_prompt = (
                "Write the FINAL outgoing chat message only. Do not discuss auditing, "
                "instructions, prompts, or missing information. Use the ORIGINAL USER REQUEST "
                "as the only factual authority. Preserve all user-provided facts and the requested "
                "tone. You may add neutral courtesy/framing for professionalism, but do not invent "
                "meetings, appointments, classes, work shifts, plans, rescheduling, promises, "
                "relationships, extra reasons, or other circumstances. No placeholders or formal "
                "letter sign-off unless requested.\n\n"
                f"ORIGINAL USER REQUEST:\n{original_request}\n\n"
                f"EXISTING DRAFT TO IMPROVE:\n{candidate}\n\n"
                "Return ONLY the final message text."
            )
            recovered = await specialist(
                [ChatMessage(Role.USER, recovery_prompt)],
                model=self.agent.loop.model,
            )
            recovered_text = recovered.text.strip().strip('"').strip()
            final_text = candidate if _looks_like_audit_meta(recovered_text) else recovered_text

        return final_text

    async def _prepare_messaging_client(self, service: str):
        from conduit.messaging.service import (
            ensure_visible_client,
            wait_until_client_ready,
            emit_messaging_stage,
        )
        await emit_messaging_stage(self.agent, service, "client_prepare", f"Starting {service.title()} messaging workflow.")
        client = await ensure_visible_client(self.agent, service)
        mode = str(client.get("mode", "")).strip()
        await emit_messaging_stage(self.agent, service, "client_opened", f"{service.title()} opened using {mode or 'visible client'} mode.")
        state, reason, evidence = await wait_until_client_ready(
            self.agent,
            service,
            client,
            timeout_seconds=90.0,
            poll_seconds=1.0,
        )
        return client, state, reason, evidence

    async def _resolve_messaging_contact(
        self,
        service: str,
        recipient: str,
        client: dict,
    ):
        from conduit.messaging.service import (
            compact_messaging_check,
            type_service_text,
            service_hotkey,
            service_press,
            open_contact_search,
            emit_messaging_stage,
        )
        if not recipient.strip():
            raise RuntimeError("I need the contact name before I can continue.")

        requested_recipient = recipient.strip()

        # Always search EXACTLY what the user asked for. Conduit never rewrites
        # "Maryam" into "Maryam Sister" or any other guessed contact name.
        await open_contact_search(self.agent, service, client)
        await emit_messaging_stage(self.agent, service, "recipient_search", f"Searching for {requested_recipient}.")
        await service_hotkey(self.agent, service, client, ("ctrl", "a"))
        search_text = requested_recipient
        await type_service_text(self.agent, service, client, search_text)

        await self.agent.tools.execute(
            ToolCall("system.wait", {"seconds": 2.0 if service == "discord" else 1.0}),
            confirmed=True,
        )

        discord_identity = None
        if service == "discord":
            # Let Discord's own Quick Switcher rank the closest/relevant DM.
            # The first result is already selected, so after re-proving keyboard
            # focus, Enter opens it. No vision matching/classification is needed.
            from conduit.messaging.service import force_service_keyboard_focus
            await force_service_keyboard_focus(self.agent, service, client, attempts=2)
            await self.agent.tools.execute(
                ToolCall("system.wait", {"seconds": 2.0}),
                confirmed=True,
            )
            await emit_messaging_stage(
                self.agent, service, "open_matching_result",
                f"Opening first Discord result for {requested_recipient}.",
            )
            await service_press(self.agent, service, client, "enter")
            await self.agent.tools.execute(
                ToolCall("system.wait", {"seconds": 2.0}),
                confirmed=True,
            )
        elif service == "whatsapp":
            # WhatsApp's contact search ranks the closest matching chat first.
            # Once focus is proven and the exact requested name has had one
            # second to populate results, Enter opens that selected first result.
            # Final chat verification below remains vision-gated, so Conduit
            # still fails closed if a real conversation did not open.
            from conduit.messaging.service import force_service_keyboard_focus
            await force_service_keyboard_focus(self.agent, service, client, attempts=2)
            await emit_messaging_stage(
                self.agent, service, "open_first_result",
                f"Opening first WhatsApp result for {requested_recipient}.",
            )
            await service_press(self.agent, service, client, "enter")
            await self.agent.tools.execute(
                ToolCall("system.wait", {"seconds": 1.0}),
                confirmed=True,
            )
        else:
            result_state, _ = await compact_messaging_check(
                self.agent, service, client,
                f"""Inspect the active {service} contact search after searching EXACTLY for
{requested_recipient!r}.

Return EXACTLY one first line:
RESULTS_READY
or
NO_RESULTS

RESULTS_READY only if at least one visible contact/chat result row exists below the
global contact search. Do not return JSON and do not choose among the results.""",
                allowed_tokens=("RESULTS_READY", "NO_RESULTS"),
            )
            if result_state != "RESULTS_READY":
                raise RuntimeError(
                    f"I couldn't see any contact results for {requested_recipient} "
                    f"in {service.title()}."
                )
            await emit_messaging_stage(self.agent, service, "results_ready", "Recipient search results are ready.")
            await emit_messaging_stage(self.agent, service, "open_first_result", "Opening the first matching direct-message result.")
            await service_press(self.agent, service, client, "down")
            await self.agent.tools.execute(ToolCall("system.wait", {"seconds": 0.15}), confirmed=True)
            await service_press(self.agent, service, client, "enter")
            await self.agent.tools.execute(ToolCall("system.wait", {"seconds": 0.8}), confirmed=True)

        # Discord's Quick Switcher + Enter path is deterministic once keyboard
        # focus is proven. Avoid another expensive vision round-trip here; the
        # user can see the opened chat before approving any outgoing message.
        if service == "discord":
            await force_service_keyboard_focus(self.agent, service, client, attempts=2)
            await emit_messaging_stage(self.agent, service, "chat_verified", "Discord chat opened.")
            return {
                "requested": requested_recipient,
                "opened": requested_recipient,
            }

        # Verify a real chat opened with a compact response for messaging services
        # whose result selection is not the deterministic Discord Quick Switcher path.
        verify_prompt = f"""Inspect the active {service} window after selecting the matching contact
search result for query {requested_recipient!r}.

Return EXACTLY:
CHAT_OPEN
CHAT_NAME <exact visible saved contact/chat header>

or exactly:
NOT_OPEN

CHAT_OPEN only if the contact search/result list is no longer the active state and a
normal conversation/message area is visibly open. Preserve the visible saved header
exactly, including spaces and emoji if present. Do not infer or rename it. No JSON."""

        open_state, open_raw = await compact_messaging_check(
            self.agent, service, client, verify_prompt,
            allowed_tokens=("CHAT_OPEN", "NOT_OPEN"),
        )

        if open_state != "CHAT_OPEN":
            raise RuntimeError(
                f"I selected the matching {service.title()} result for "
                f"{requested_recipient}, but I couldn't verify that the chat "
                "actually opened, so I did not claim success."
            )

        await emit_messaging_stage(self.agent, service, "chat_verified", "Direct-message chat opened and was verified.")
        opened_name = requested_recipient
        for line in open_raw.splitlines()[1:]:
            line = line.strip()
            if line.upper().startswith("CHAT_NAME "):
                candidate = line[len("CHAT_NAME "):].strip()
                if candidate and len(candidate) <= 120:
                    opened_name = candidate
                break

        return {
            "requested": requested_recipient,
            "opened": opened_name,
        }

    async def _execute_messaging_plan(self, user_message: str, plan: MessagingPlan):
        service = plan.service
        recipient = plan.recipient or self._messaging_context.get("recipient", "")

        # Preserve task-level messaging context BEFORE UI execution. This lets a
        # correction such as "try khokhar goli" continue the failed WhatsApp
        # contact lookup instead of being reinterpreted as an unrelated request.
        self._messaging_context.update({
            "service": service,
            "last_action": plan.action,
        })
        if recipient:
            self._messaging_context["attempted_recipient"] = recipient

        try:
            client, readiness_state, readiness_reason, readiness_evidence = await self._prepare_messaging_client(service)
        except Exception as exc:
            msg = str(exc)
            return f"I couldn't prepare {service.title()}: {msg}", DirectConversationReport(_MessagingStatus(), success=False, final_message=msg)
        if readiness_state != "ready":
            if readiness_state == "logged_out":
                answer = (
                    f"{service.title()} isn't logged in. I left the login page/client "
                    "open in front of you. Log in first, then ask me to continue."
                )
                final = "Messaging login required."
            elif readiness_state == "timeout":
                answer = (
                    f"I opened {service.title()}, but it still wasn't ready after waiting "
                    "for it to finish loading, so I stopped before searching for any contact."
                )
                final = "Messaging client readiness timed out."
            elif readiness_state == "error":
                answer = (
                    f"{service.title()} opened, but I detected an error or the app closed "
                    "before it became ready, so I stopped."
                )
                final = "Messaging client failed before becoming ready."
            else:
                answer = (
                    f"I opened {service.title()}, but I couldn't safely verify that the "
                    "chat interface was ready, so I stopped before searching for any contact."
                )
                final = "Messaging client readiness could not be verified."
            return answer, DirectConversationReport(
                _MessagingStatus(), success=False, final_message=final
            )
        try:
            resolution = await self._resolve_messaging_contact(service, recipient, client)
            resolved = resolution["opened"]
            requested_recipient = resolution["requested"]
        except Exception as exc:
            msg = str(exc)
            return msg, DirectConversationReport(_MessagingStatus(), success=False, final_message=msg)

        self._messaging_context.update({
            "service": service,
            "recipient": resolved,
            "requested_recipient": requested_recipient,
            "attempted_recipient": requested_recipient,
            "last_action": plan.action,
        })
        if plan.action in ("messaging.resolve_contact", "messaging.open_chat"):
            if resolved.casefold() != requested_recipient.casefold():
                answer = (
                    f"I opened the first {service.title()} search result for "
                    f"{requested_recipient}: {resolved}."
                )
            else:
                answer = (
                    f"I opened the first {service.title()} search result for "
                    f"{requested_recipient}."
                )
            return answer, DirectConversationReport(_MessagingStatus(), final_message=answer)

        if plan.action == "messaging.read_recent":
            from conduit.messaging.service import observe_service_screen
            analysis = await observe_service_screen(
                self.agent,
                service,
                client,
                f"Read only the visibly present recent messages in the open {service} chat with {resolved}. Distinguish incoming/outgoing when clear.",
            )
            visible = "\n".join((e.text or e.label).strip() for e in analysis.elements if (e.text or e.label or "").strip())
            response = await self.agent.loop.provider.chat(
                [ChatMessage(Role.USER, f"Summarize these visibly retrieved recent messages conversationally. Do not invent anything.\n\n{visible}")],
                model=self.agent.loop.model,
            )
            answer = response.text.strip()
            return answer, DirectConversationReport(_MessagingStatus(), final_message=answer)

        final_message = await self._compose_messaging_text(user_message, plan)

        # IMPORTANT: do NOT type or paste anything into the messenger yet.
        # The entire draft stays only in Conduit's memory until the user approves
        # the exact text below. This prevents multiline drafts from being sent
        # piece-by-piece by Enter/newline handling.
        self._messaging_context.update({
            "pending_message": final_message,
            "pending_recipient": resolved,
            "pending_service": service,
            "pending_client_mode": str(client.get("mode", "")),
            "pending_window_title": str(client.get("window_title", "")),
            "pending_window_handle": str(client.get("window_handle", 0) or 0),
        })
        answer = f"I've prepared this message for {resolved} on {service.title()}:\n\n{final_message}\n\nSend it? Type YES to send or NO to cancel."
        return answer, DirectConversationReport(_MessagingStatus(), final_message="Message prepared; explicit send confirmation required.")

    async def confirm_pending_message(self, approved: bool):
        pending = self._messaging_context.get("pending_message", "")
        recipient = self._messaging_context.get("pending_recipient", "")
        service = self._messaging_context.get("pending_service", "")
        client = {
            "mode": self._messaging_context.get("pending_client_mode", ""),
            "window_title": self._messaging_context.get("pending_window_title", ""),
            "window_handle": int(self._messaging_context.get("pending_window_handle", "0") or 0),
        }
        if not pending:
            msg = "There isn't a message waiting to be sent."
            return msg, DirectConversationReport(
                _MessagingStatus(), success=False, final_message=msg
            )

        if not approved:
            # Nothing has been typed into the messenger yet, so cancellation is
            # a pure in-memory discard with no external side effect.
            for key in (
                "pending_message", "pending_recipient", "pending_service",
                "pending_client_mode", "pending_window_title", "pending_window_handle",
            ):
                self._messaging_context.pop(key, None)
            msg = "Okay, I cancelled the message. Nothing was sent."
            return msg, DirectConversationReport(
                _MessagingStatus(), final_message=msg
            )

        from conduit.messaging.service import (
            compact_messaging_check,
            ensure_service_foreground,
            service_hotkey,
            service_press,
        )

        # The user has now approved the ENTIRE exact draft. Only now may Conduit
        # place it in the messenger. Clipboard paste is atomic from WhatsApp's
        # perspective and preserves multiline text without each newline acting
        # as a separate Send/Enter.
        await ensure_service_foreground(self.agent, service, client, attempts=3)
        clip = await self.agent.tools.execute(
            ToolCall("clipboard.write", {"text": pending}),
            confirmed=True,
        )
        if not getattr(clip, "success", False):
            msg = "I couldn't prepare the approved message on the clipboard, so I did not send anything."
            return msg, DirectConversationReport(
                _MessagingStatus(), success=False, final_message=msg
            )

        await service_hotkey(self.agent, service, client, ("ctrl", "v"))
        await self.agent.tools.execute(
            ToolCall("system.wait", {"seconds": 1.0 if service == "whatsapp" else 0.35}),
            confirmed=True,
        )

        # Verify the WHOLE approved draft is present before the one Send action.
        draft_state, _ = await compact_messaging_check(
            self.agent,
            service,
            client,
            f"""Inspect the active {service} chat.
Is the COMPLETE exact approved draft below visibly present in the OUTGOING
message composer as one pending draft?

APPROVED DRAFT:
{pending}

Return EXACTLY one first line:
DRAFT_PRESENT
or
DRAFT_MISSING

Do not count matching text in chat history. No JSON.""",
            allowed_tokens=("DRAFT_PRESENT", "DRAFT_MISSING"),
        )
        if draft_state != "DRAFT_PRESENT":
            msg = (
                "I pasted the approved draft, but I couldn't verify the complete "
                f"message in {service.title()}, so I did not press Send."
            )
            return msg, DirectConversationReport(
                _MessagingStatus(), success=False, final_message=msg
            )

        await service_press(self.agent, service, client, "enter")

        # WhatsApp fast path: the safety-critical verification has already happened
        # BEFORE Send, proving the exact approved draft is present in the composer.
        # Once WhatsApp still owns focus and the single Enter action executes,
        # avoid another expensive vision round-trip just to watch the sent bubble
        # appear. This makes completion immediate while preserving the pre-send
        # safety guarantee. Other messaging services keep visual sent verification.
        if service == "whatsapp":
            await self.agent.tools.execute(
                ToolCall("system.wait", {"seconds": 0.25}),
                confirmed=True,
            )
            verified = True
        else:
            await self.agent.tools.execute(
                ToolCall("system.wait", {"seconds": 0.8}),
                confirmed=True,
            )
            sent_state, _ = await compact_messaging_check(
                self.agent,
                service,
                client,
                f"""Inspect the active {service} chat after the single Send action.
Is the COMPLETE exact approved draft below visibly present as an outgoing/sent
message (one message, even if it contains line breaks)?

APPROVED DRAFT:
{pending}

Return EXACTLY one first line:
SENT_PRESENT
or
SENT_MISSING

No JSON.""",
                allowed_tokens=("SENT_PRESENT", "SENT_MISSING"),
            )
            verified = sent_state == "SENT_PRESENT"

        for key in (
            "pending_message", "pending_recipient", "pending_service",
            "pending_client_mode", "pending_window_title", "pending_window_handle",
        ):
            self._messaging_context.pop(key, None)

        if verified:
            msg = f"Sent to {recipient} on {service.title()}."
            return msg, DirectConversationReport(
                _MessagingStatus(), final_message=msg
            )

        msg = (
            f"I pressed Send for {recipient}, but I couldn't visually verify that "
            "the message appeared as sent. Please check the open chat."
        )
        return msg, DirectConversationReport(
            _MessagingStatus(),
            success=False,
            final_message="Send verification inconclusive.",
        )

    def _could_be_youtube_request(self, current: str) -> bool:
        lowered = current.casefold()
        direct_terms = (
            "youtube", "youtu.be", "youtube.com", " on yt", " yt ", "video", "transcript",
            "song", "music", "track",
            "trending videos", "livestream", "live stream", "pause the video", "resume the video",
            "pause video", "resume video", "playback",
        )
        if any(term in lowered for term in direct_terms):
            return True
        # Short referential follow-ups such as "pause it" are only considered
        # YouTube requests when recent conversation was clearly about YouTube.
        referential = any(
            term in f" {lowered} "
            for term in (" pause it ", " resume it ", " play it ", " summarize it ")
        )
        if referential and self.history:
            recent = " ".join(
                f"{turn.user} {turn.assistant}"
                for turn in self.session_memory.recent_turns(2)
            ).casefold()
            return "youtube" in recent or "video" in recent
        return False

    async def _make_youtube_plan(
        self,
        current: str,
        *,
        needs_history: bool,
    ) -> YouTubePlan | None:
        context = ""
        if needs_history or self.history:
            context = "\n".join(
                f"User: {turn.user}\nConduit: {turn.assistant}"
                for turn in self.session_memory.recent_turns(2)
            )
        # Latest matching episode/show requests carry strict semantic constraints
        # (especially an explicitly named channel). Route these deterministically
        # BEFORE the AI router so the model cannot accidentally drop the channel
        # or degrade the request into a generic youtube.play action.
        deterministic = self._fallback_youtube_plan(current)
        if deterministic is not None and deterministic.action in {
            "youtube.play_latest_matching",
            "youtube.play_matching_video",
            "youtube.pause",
            "youtube.resume",
        }:
            return deterministic

        router = AIYouTubeRouter(
            self.agent.loop.provider,
            self.agent.loop.model,
        )
        try:
            return await router.plan(current, recent_context=context)
        except Exception:
            return deterministic or self._fallback_youtube_plan(current)

    @staticmethod
    def _fallback_youtube_plan(current: str) -> YouTubePlan | None:
        lowered = current.casefold()
        if "pause" in lowered:
            return YouTubePlan("youtube.pause", {})
        if "resume" in lowered:
            return YouTubePlan("youtube.resume", {})
        def channel_after_marker(text: str) -> str | None:
            for marker in (" from channel ", " from ", " of channel ", " of "):
                if marker in text.casefold():
                    idx = text.casefold().rfind(marker)
                    value = text[idx + len(marker):].strip()
                    if value:
                        return value
            return None

        channel = channel_after_marker(current)
        if ("live stream" in lowered or "livestream" in lowered or "streaming right now" in lowered) and channel:
            return YouTubePlan("youtube.play_live", {"channel": channel})
        if ("most popular" in lowered or "most viewed" in lowered) and channel:
            return YouTubePlan("youtube.play_most_popular", {"channel": channel})
        if ("oldest" in lowered or "first video" in lowered or "first upload" in lowered) and channel:
            return YouTubePlan("youtube.play_oldest_upload", {"channel": channel})
        # Topic/episode newest-match requests are different from "latest upload
        # from channel X": search the topic and compare recency among relevant results.
        if ("latest" in lowered or "newest" in lowered) and any(
            term in lowered for term in ("episode", "drama", "serial", "show")
        ):
            import re as _re
            channel_match = _re.search(
                r"(?i)\b(?:from|form)\s+channel\s+(.+?)\s*$",
                current,
            )
            scoped_channel = channel_match.group(1).strip() if channel_match else ""
            query = current
            if scoped_channel:
                query = _re.sub(
                    r"(?i)\b(?:from|form)\s+channel\s+.+?\s*$",
                    "",
                    query,
                ).strip()
            query = _re.sub(r"(?i)^\s*(?:open\s+youtube\s+and\s+)?play\s+", "", query).strip()
            query = _re.sub(r"(?i)\b(?:the\s+)?(?:latest|newest)\b", "", query).strip()
            return YouTubePlan(
                "youtube.play_latest_matching",
                {"query": query or current, **({"channel": scoped_channel} if scoped_channel else {})},
            )
        if ("latest" in lowered or "newest" in lowered) and ("upload" in lowered or "video" in lowered) and channel:
            return YouTubePlan("youtube.play_latest_upload", {"channel": channel})
        if re.search(r"(?i)\bplay\b", current) and any(
            term in lowered for term in ("song", "music", "track")
        ):
            import re as _re
            query = _re.sub(
                r"(?i)^\s*(?:please\s+)?play\s+(?:the\s+)?(?:song|music|track)\s+",
                "",
                current,
            ).strip()
            if not query:
                query = current
            return YouTubePlan(
                "youtube.play_matching_video",
                {"description": current, "search_query": query},
            )

        descriptive_markers = (
            "i saw a video", "find the video where", "find that video",
            "video where", "video in which", "there was a video",
            "remember a video", "looking for a video",
        )
        if any(marker in lowered for marker in descriptive_markers):
            return YouTubePlan(
                "youtube.play_matching_video",
                {"description": current, "search_query": current},
            )
        if "transcript" in lowered:
            return YouTubePlan("youtube.get_transcript", {"video": current}, True)
        if "summar" in lowered:
            return YouTubePlan("youtube.summarize", {"video": current}, True)
        if "trending" in lowered:
            return YouTubePlan("youtube.trending", {}, True)
        if "search" in lowered and "youtube" in lowered:
            return YouTubePlan("youtube.search", {"query": current}, True)
        if "play" in lowered and ("youtube" in lowered or "video" in lowered):
            return YouTubePlan("youtube.play", {"video": current})
        return None

    async def _execute_youtube_plan(
        self,
        user_message: str,
        plan: YouTubePlan,
    ) -> tuple[str, DirectConversationReport]:
        if plan.action == "youtube.play_matching_video":
            return await self._execute_youtube_description_match(user_message, plan)

        outcome = await self.agent.tools.execute(
            ToolCall(plan.action, plan.arguments),
            confirmed=True,
        )
        if not getattr(outcome, "success", False):
            message = getattr(outcome, "message", f"{plan.action} did not complete.")
            report = DirectConversationReport(
                status=_YouTubeStatus(),
                success=False,
                final_message=message,
            )
            return f"I couldn't complete that YouTube request: {message}", report

        data = dict(getattr(outcome, "data", {}) or {})
        message = str(getattr(outcome, "message", "YouTube action completed."))

        if plan.needs_synthesis:
            answer = await self._synthesize_youtube_result(
                user_message,
                plan.action,
                data,
            )
        else:
            if plan.action in {
                "youtube.play", "youtube.play_latest_upload",
                "youtube.play_oldest_upload", "youtube.play_most_popular",
                "youtube.play_live", "youtube.play_matching_video",
                "youtube.play_latest_matching",
            }:
                title = str(data.get("title") or data.get("video_title") or "the video")
                answer = f"I opened {title} in your default browser."
            elif plan.action == "youtube.pause":
                answer = "I paused the YouTube playback."
            elif plan.action == "youtube.resume":
                answer = "I resumed the YouTube playback."
            else:
                answer = message

        report = DirectConversationReport(
            status=_YouTubeStatus(),
            success=True,
            final_message=message,
        )
        return answer, report

    async def _execute_youtube_description_match(
        self,
        user_message: str,
        plan: YouTubePlan,
    ) -> tuple[str, DirectConversationReport]:
        """Search several candidates, AI-rerank them, then open the best match."""
        description = str(plan.arguments.get("description") or user_message).strip()
        search_query = str(plan.arguments.get("search_query") or description).strip()
        channel = str(plan.arguments.get("channel") or "").strip()
        if channel and channel.casefold() not in search_query.casefold():
            search_query = f"{channel} {search_query}".strip()

        search_outcome = await self.agent.tools.execute(
            ToolCall("youtube.search", {"query": search_query, "limit": 8}),
            confirmed=True,
        )
        if not getattr(search_outcome, "success", False):
            message = getattr(search_outcome, "message", "YouTube search failed.")
            return (
                f"I couldn't find that YouTube video: {message}",
                DirectConversationReport(
                    status=_YouTubeStatus(),
                    success=False,
                    final_message=message,
                ),
            )

        videos = list((getattr(search_outcome, "data", {}) or {}).get("videos", []) or [])
        if not videos:
            message = "No YouTube candidates matched the remembered video description."
            return (
                f"I couldn't find a close match for that video description.",
                DirectConversationReport(
                    status=_YouTubeStatus(),
                    success=False,
                    final_message=message,
                ),
            )

        candidates = []
        for index, item in enumerate(videos[:8], 1):
            if not isinstance(item, dict):
                continue
            candidates.append(
                {
                    "index": index,
                    "title": str(item.get("title") or ""),
                    "channel": str(item.get("channel") or ""),
                    "url": str(item.get("url") or ""),
                    "duration": item.get("duration"),
                    "view_count": item.get("view_count"),
                }
            )

        chosen_index = 1
        try:
            prompt = (
                "You are Conduit's YouTube VIDEO MATCHER. The user remembers a video "
                "but may not know its exact title. Choose the single candidate that best "
                "matches the remembered description. Judge semantic meaning, important "
                "objects/events/challenge details, named creator/channel when provided, "
                "and title similarity. Do not invent candidates. If several are plausible, "
                "prefer the higher-ranked YouTube search result. Return ONLY JSON like "
                '{"index":2,"reason":"short reason","confidence":0.82}.\\n\\n'
                f"USER DESCRIPTION:\n{description}\n\n"
                f"OPTIONAL CHANNEL:\n{channel}\n\n"
                f"SEARCH QUERY:\n{search_query}\n\n"
                f"CANDIDATES:\n{json.dumps(candidates, ensure_ascii=False)}"
            )
            response = await self.agent.loop.provider.chat(
                [ChatMessage(Role.USER, prompt)],
                model=self.agent.loop.model,
            )
            raw = response.text.strip()
            import re as _re
            match = _re.search(r"\{.*\}", raw, flags=_re.S)
            if match:
                parsed = json.loads(match.group(0))
                idx = int(parsed.get("index", 1))
                if 1 <= idx <= len(candidates):
                    chosen_index = idx
        except Exception:
            chosen_index = 1

        chosen = candidates[chosen_index - 1]
        url = chosen.get("url", "")
        if not url:
            message = "The best matching YouTube result did not contain a playable URL."
            return (
                "I found a likely match, but I couldn't open it.",
                DirectConversationReport(
                    status=_YouTubeStatus(),
                    success=False,
                    final_message=message,
                ),
            )

        play_outcome = await self.agent.tools.execute(
            ToolCall("youtube.play", {"video": url}),
            confirmed=True,
        )
        if not getattr(play_outcome, "success", False):
            message = getattr(play_outcome, "message", "Unable to open the matched video.")
            return (
                f"I found a likely match but couldn't open it: {message}",
                DirectConversationReport(
                    status=_YouTubeStatus(),
                    success=False,
                    final_message=message,
                ),
            )

        title = str(chosen.get("title") or "the matching video")
        answer = f"I found the closest match to what you described and opened {title} in your default browser."
        return (
            answer,
            DirectConversationReport(
                status=_YouTubeStatus(),
                success=True,
                final_message=f"Matched and opened {title}.",
            ),
        )

    async def _synthesize_youtube_result(
        self,
        user_message: str,
        action: str,
        data: dict[str, Any],
    ) -> str:
        payload = json.dumps(data, ensure_ascii=False)
        if len(payload) > self.max_observation_chars:
            payload = payload[: self.max_observation_chars] + "...[truncated]"

        prompt = (
            "You are Conduit. Answer the user's YouTube request from the structured "
            "YouTube evidence below. Do not claim you watched or heard content that "
            "was not retrieved. For summaries, summarize the transcript evidence. "
            "For search/trending/info, give the useful result directly. Default to "
            "one to three natural conversational paragraphs with no headings, lists, "
            "or tables unless the user explicitly requested them. Be concise and "
            "voice-friendly.\n\n"
            f"USER REQUEST:\n{user_message}\n\n"
            f"YOUTUBE ACTION:\n{action}\n\n"
            f"STRUCTURED EVIDENCE:\n{payload}"
        )
        response = await self.agent.loop.provider.chat(
            [ChatMessage(Role.USER, prompt)],
            model=self.agent.loop.model,
        )
        answer = response.text.strip()
        return answer or "I retrieved the YouTube information, but couldn't summarize it clearly."

    async def _make_intent_plan(
        self,
        current: str,
        *,
        needs_history: bool,
    ) -> IntentPlan:
        context = ""
        if needs_history:
            context = "\n".join(
                f"User: {turn.user}\nConduit: {turn.assistant}"
                for turn in self.session_memory.recent_turns(2)
            )
        router = AIIntentRouter(
            self.agent.loop.provider,
            self.agent.loop.model,
        )
        try:
            return await router.plan(
                current,
                recent_context=context,
            )
        except Exception:
            route = self._route_turn(current)
            return IntentPlan(
                route=route,
                web_needed=bool(self._conversation_web_actions(current)),
                browser_requested=False,
                normalized_request=current,
                intent="fallback",
            )

    @staticmethod
    def _sources_or_verification_requested(current: str) -> bool:
        lowered = f" {current.casefold()} "
        return any(
            term in lowered
            for term in (
                " source ", " sources ", " cite ", " citation ", " citations ",
                " verify ", " verified ", " evidence ",
            )
        )

    async def _build_evidence_hypothesis(
        self,
        current: str,
        *,
        include_history: bool,
    ) -> str:
        """Ask the active model what it currently believes before retrieval.

        This is intentionally untrusted. Its purpose is to give the search planner
        concrete candidate entities/claims to verify, so retrieval can correct stale
        model knowledge instead of replacing reasoning with generic snippets.
        """
        history = ""
        if include_history and self.history:
            history = "\n".join(
                f"User: {turn.user}\nConduit: {turn.assistant}"
                for turn in self.session_memory.recent_turns(2)
            )
        prompt = (
            "You are Conduit's PRE-RETRIEVAL REASONER. Do not give a user-facing answer. "
            "State a compact preliminary hypothesis for the CURRENT request from model "
            "knowledge: likely answer, candidate entities, and concrete claims/numbers "
            "that should be checked. This may be outdated, so label uncertainty internally. "
            "Do not invent URLs or sources. Keep it under 180 words.\n\n"
            + (f"RECENT CONTEXT:\n{history}\n\n" if history else "")
            + f"CURRENT REQUEST:\n{current}"
        )
        try:
            response = await self.agent.loop.provider.chat(
                [ChatMessage(Role.USER, prompt)],
                model=self.agent.loop.model,
            )
            return response.text.strip()[:3000]
        except Exception:
            return ""

    async def _make_search_plan(
        self,
        current: str,
        *,
        needs_history: bool,
        allowed_actions: set[str] | None = None,
        evidence_hypothesis: str = "",
    ) -> SearchPlan:
        context = ""
        if needs_history:
            context = "\n".join(
                f"User: {turn.user}\nConduit: {turn.assistant}"
                for turn in self.session_memory.recent_turns(2)
            )
        planner = AISearchPlanner(
            self.agent.loop.provider,
            self.agent.loop.model,
        )
        try:
            return await planner.plan(
                current,
                recent_context=context,
                allowed_actions=allowed_actions,
                evidence_hypothesis=evidence_hypothesis,
            )
        except Exception:
            return self._fallback_search_plan(current)

    def _fallback_search_plan(self, current: str) -> SearchPlan:
        actions = self._required_web_actions(current) or self._conversation_web_actions(current)
        action = next(iter(actions), "web.search")
        lowered = current.casefold()
        detailed = any(
            term in lowered
            for term in (
                "detailed", "in detail", "full breakdown", "exhaustive",
                "step by step", "comprehensive report",
            )
        )
        sources_requested = any(
            term in lowered
            for term in ("source", "sources", "cite", "citation", "research", "studies")
        )
        if action == "web.price_search":
            arguments = {"item": current, "region": "", "currency": "", "limit": 10}
        elif action == "web.news":
            arguments = {"query": current, "limit": 12, "parallel_queries": 3}
        elif action == "web.research":
            arguments = {"query": current, "depth": 2, "sources_per_query": 5, "use_grounding": True}
        elif action == "web.compare":
            arguments = {"items": [], "criteria": [], "region": "", "include_prices": True}
        else:
            arguments = {"query": current, "limit": 8, "use_grounding": True, "region": "wt-wt"}
        return SearchPlan(
            action=action,
            arguments=arguments,
            intent="fallback",
            subject=current,
            rewritten_request=current,
            answer_style="detailed" if detailed else "concise",
            sources_requested=sources_requested,
            notes=("AI search planning was unavailable; conservative fallback used.",),
        )

    def _goal_from_search_plan(
        self,
        current: str,
        plan: SearchPlan,
        *,
        include_history: bool,
    ) -> str:
        history_note = ""
        if include_history and self.history:
            history_note = (
                "\nThe plan already resolved explicit references from recent context; "
                "do not substitute any older topic."
            )
        return (
            "Execute the AI-normalized web plan for the CURRENT user request. "
            "Use exactly the planned action and arguments. Do not open a visible browser. "
            "Do not replace the planned subject with any previous conversation topic."
            + history_note
            + "\n\nCURRENT USER REQUEST:\n"
            + current
            + "\n\nAI SEARCH PLAN:\n"
            + json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
        )

    def _remember_turn(self, user: str, assistant: str) -> None:
        # One canonical exact-session copy: temporary SQLite. `history` is only
        # a list-like view over this store, not a second in-memory transcript.
        self.session_memory.add(user, assistant)
        self._remember_latest_artifact(assistant)
        if self.long_term_learner is not None:
            self.long_term_learner.observe(user, assistant)

    def _history_text(self, limit: int = 4) -> str:
        """Render recent conversation turns for intent routers.

        This is short-lived conversational context, separate from Conduit's
        persistent long-term memory database.
        """
        history = getattr(self, "history", ())
        if not history:
            return getattr(self, "resume_context", "")
        lines: list[str] = []
        session_memory = getattr(self, "session_memory", None)
        if session_memory is not None and getattr(history, "store", None) is session_memory:
            turns = session_memory.recent_turns(max(1, int(limit)))
        else:
            turns = list(history)[-max(1, int(limit)):]
        for turn in turns:
            lines.append(f"User: {turn.user}")
            lines.append(f"Conduit: {turn.assistant}")
        if self.resume_context:
            lines.insert(0, "Previous-session recap: " + self.resume_context)
        return "\n".join(lines)

    @staticmethod
    def _ordinal_index(word: str) -> int | None:
        value = word.casefold().strip()
        mapping = {
            "first": 0, "1st": 0, "one": 0,
            "second": 1, "2nd": 1, "two": 1,
            "third": 2, "3rd": 2, "three": 2,
            "fourth": 3, "4th": 3, "four": 3,
            "fifth": 4, "5th": 4, "five": 4,
            "last": -1,
        }
        if value in mapping:
            return mapping[value]
        if value.isdigit():
            number = int(value)
            return max(0, number - 1)
        return None

    def _session_recall_answer(self, current: str) -> str | None:
        """Answer exact transcript questions without relying on model inference."""
        lower = " ".join(current.casefold().split())
        if not self.history:
            if any(x in lower for x in ("conversation", "did i ask", "did you say", "asked you")):
                return "There isn't an earlier turn in this conversation yet."
            return None

        # Resolve identity questions directly from persistent memory when available.
        # This prevents the active model from claiming it does not know the user's
        # name simply because the model did not independently infer the memory fact.
        if lower in {"what is my name", "what's my name", "whats my name",
                     "who am i", "do you know my name", "remember my name"}:
            manager = getattr(self, "memory_manager", None)
            if manager is not None:
                try:
                    from conduit.memory.models import MemoryCategory
                    record = manager.repository.get_memory(MemoryCategory.PREFERENCE, "user:name")
                    if record is not None and str(record.value).strip():
                        return f"Your name is {record.value.strip()}."
                except Exception:
                    pass
            # Session-only fallback when persistent memory is disabled/unavailable.
            for turn in self.session_memory.recent_turns(20):
                for pattern in (
                    r"(?i)\b(?:my\s+name\s+is|call\s+me)\s+([A-Za-z][A-Za-z\'-]{0,59}?)(?=\s+(?:and|but|because|i|i\'m|i\s+am|nad)\b|[.!?,;]|$)",
                    r"(?i)\b(?:i\s+am|i\'m)\s+([A-Za-z][A-Za-z\'-]{0,59}?)(?=\s+(?:and|but|because|i|i\'m|i\s+am|nad)\b|[.!?,;]|$)",
                ):
                    match = re.search(pattern, turn.user)
                    if match:
                        return f"Your name is {match.group(1).strip()}."

        # Resolve common profile/preference recall directly from long-term memory.
        # The learner itself is general; these shortcuts only prevent a weak active
        # model from contradicting facts Conduit has already stored.
        if lower in {"what do i like", "what do i like to do", "what do i enjoy",
                     "what are my interests", "what am i interested in"}:
            manager = getattr(self, "memory_manager", None)
            if manager is not None:
                try:
                    from conduit.memory.models import MemoryCategory
                    records = [r for r in manager.repository.list_memories()
                               if r.category is MemoryCategory.PREFERENCE and
                               (r.key == "user:likes" or r.key.startswith("user:favorite:"))]
                    if records:
                        values = []
                        for record in records[:6]:
                            value = str(record.value).strip()
                            if value and value.casefold() not in {v.casefold() for v in values}:
                                values.append(value)
                        if values:
                            return "You like " + ", ".join(values[:-1]) + ((" and " + values[-1]) if len(values) > 1 else values[0] if not values[:-1] else "") + "."
                except Exception:
                    pass
            # Session fallback catches explicit likes even if persistent memory is off.
            for turn in reversed(self.session_memory.recent_turns(20)):
                match = re.search(r"(?i)\bi\s+(?:really\s+)?(?:like|love|enjoy)\s+(?:to\s+)?(.+?)(?=[.!?;]|$)", turn.user)
                if match:
                    value = " ".join(match.group(1).split()).strip(" .,!?:;")
                    value = re.split(r"(?i)\s+(?:and|but|nad)\s+(?=i\b|my\b)", value, maxsplit=1)[0].strip()
                    if value:
                        return f"You like {value}."

        # What did I ask first/second/...?
        patterns = (
            r"\bwhat\s+did\s+i\s+(?:ask|say|tell\s+you)\s+(?:you\s+)?(?:the\s+)?"
            r"(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th|\d+)(?:\s+time)?\b",
            r"\bwhat\s+was\s+my\s+(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th|\d+)"
            r"\s+(?:question|request|message|prompt)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                idx = self._ordinal_index(match.group(1))
                turn = self.session_memory.turn_at(idx if idx is not None else 0)
                if turn is None:
                    return "That turn doesn't exist in this conversation."
                label = match.group(1)
                return f"Your {label} message in this conversation was: {turn.user}"

        # What did you answer to my first/second/...?
        match = re.search(
            r"\bwhat\s+did\s+you\s+(?:answer|reply|say)\s+(?:to|after)\s+(?:my\s+)?"
            r"(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th|\d+)"
            r"(?:\s+(?:question|request|message|prompt))?\b",
            lower,
        )
        if match:
            idx = self._ordinal_index(match.group(1))
            turn = self.session_memory.turn_at(idx if idx is not None else 0)
            if turn is None:
                return "That turn doesn't exist in this conversation."
            return f"My reply to your {match.group(1)} message was: {turn.assistant}"

        # Exact first/last conversation aliases.
        if lower in {
            "what did i ask first", "what did i ask you first",
            "what was the first thing i asked", "what was my first message",
            "what was my first question", "what was my first request",
        }:
            turn = self.session_memory.turn_at(0)
            return f"Your first message in this conversation was: {turn.user}" if turn else None

        # Broad history questions should be sent to the model WITH session context.
        return None

    @staticmethod
    def _message_needs_history(current: str) -> bool:
        """Return whether prior turns may help interpret the current message.

        Natural conversation often depends on facts stated moments earlier even
        without pronouns such as "that" or phrases such as "what did I say".
        Identity/profile recall questions are therefore explicitly history-aware.
        """

        lowered = f" {current.casefold()} "
        normalized = re.sub(r"[^a-z0-9]+", " ", current.casefold()).strip()
        identity_recall = {
            "what is my name",
            "whats my name",
            "what s my name",
            "who am i",
            "do you know my name",
            "remember my name",
            "what do i like",
            "what do i like to do",
            "what do i enjoy",
            "what are my interests",
            "what am i interested in",
        }
        if normalized in identity_recall:
            return True
        reference_phrases = (
            " that ",
            " it ",
            " them ",
            " those ",
            " these ",
            " the first one ",
            " the second one ",
            " which one ",
            " which is better ",
            " compare it ",
            " compare that ",
            " what about ",
            " how about ",
            " based on what we found ",
            " from before ",
            " previous result ",
            " earlier result ",
            " same one ",
            " same product ",
            " same topic ",
            " try ",
            " try this ",
            " try that ",
            " try again ",
            " send it ",
            " tell him ",
            " tell her ",
            " message him ",
            " message her ",
            " conversation ",
            " what did i ask ",
            " what did i say ",
            " what did you say ",
            " what did you answer ",
            " what did we talk about ",
            " what have we talked about ",
            " earlier in this conversation ",
            " beginning of the conversation ",
            " start of the conversation ",
            " first message ",
            " first question ",
            " first request ",
            " what was my first ",
            " what was my second ",
            " what was my third ",
            " what was my last ",
            " last message ",
        )
        return any(phrase in lowered for phrase in reference_phrases)

    def _resolved_request_text(
        self,
        current: str,
        needs_history: bool,
    ) -> str:
        """Return current text unchanged unless references truly require history."""

        if not needs_history or not self.history:
            return current

        context = self.session_memory.context_for(
            current, recent_turns=max(8, self.max_history_turns), relevant_older=10
        )
        return (
            "Resolve references in the current request using this current-session memory.\n"
            + context
            + "\nCurrent request: "
            + current
        )

    @staticmethod
    def _is_weather_browser_lookup(current: str) -> bool:
        lowered = current.casefold()
        weather = any(
            term in lowered
            for term in ("weather", "forecast", "temperature", "rain today", "will it rain")
        )
        research = any(
            term in lowered
            for term in (
                "climate research", "historical weather", "weather history",
                "climate trend", "study", "studies", "research", "sources",
            )
        )
        return weather and not research

    async def _open_weather_in_browser(self, normalized_request: str) -> str:
        query = " ".join(normalized_request.split()).strip()
        if "weather" not in query.casefold() and "forecast" not in query.casefold():
            query = f"{query} weather"
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)

        # Visible browsing policy: hand the URL to Windows itself. Windows then
        # opens the user's configured default browser. If that browser is already
        # running, its normal URL handling decides whether to reuse the window/new
        # tab. Never start the Playwright-managed Chromium for visible browsing.
        outcome = await self.agent.tools.execute(
            ToolCall("system.open_url", {"url": url}),
            confirmed=True,
        )
        if not getattr(outcome, "success", False):
            raise RuntimeError(getattr(outcome, "message", "Unable to open the URL."))

        events = getattr(self.agent, "events", None)
        if events is not None and hasattr(events, "emit"):
            await events.emit(
                "conversation.weather.opened",
                source="ConversationSession",
                payload={
                    "query": query,
                    "url": url,
                    "browser_policy": "windows_default",
                },
            )
        return (
            "I opened the weather search in your default browser so you can see "
            "the current conditions directly."
        )


    @staticmethod
    def _strict_verification_requested(current: str) -> bool:
        lowered = current.casefold()
        asks_verification = any(
            term in lowered
            for term in ("verify", "verified", "exact", "sources", "citations", "cite")
        )
        factual_specs = any(
            term in lowered
            for term in (
                "spec", "specification", "vram", "memory bus", "power",
                "tdp", "hardware", "clock", "bandwidth", "version",
            )
        )
        return asks_verification and factual_specs

    @staticmethod
    def _required_web_actions(current: str) -> set[str]:
        """Hard reliability boundary for requests that inherently need live evidence.

        This classifies capability only; subjects/queries still come from the AI planner.
        """
        lowered = f" {current.casefold()} "

        price_terms = (
            " price ", " prices ", " cost ", " how much ",
            " market price ", " in stock ", " availability ",
        )
        news_terms = (" news ", " headlines ", " breaking ", " latest news ")
        research_terms = (
            " studies ", " study ", " research ", " papers ", " paper ",
            " peer reviewed ", " peer-reviewed ", " evidence ",
        )
        source_terms = (
            " sources ", " source ", " citations ", " citation ",
            " cite ", " verify ", " verified ",
        )
        live_terms = (
            " right now ", " rn ", " today ",
            " currently ", " current ", " latest ",
        )
        comparison = any(
            term in lowered for term in (" compare ", " comparison ", " vs ", " versus ")
        )

        if any(term in lowered for term in price_terms):
            return {"web.price_search"}
        if any(term in lowered for term in news_terms):
            return {"web.news"}
        if comparison and any(term in lowered for term in source_terms + live_terms):
            return {"web.compare"}
        if any(term in lowered for term in research_terms):
            return {"web.research"}
        if any(term in lowered for term in source_terms + live_terms):
            return {"web.search"}
        return set()

    def _route_turn(self, current: str) -> str:
        """Choose direct reasoning, structured tools, or hybrid reasoning.

        Classification is based on the CURRENT message only. Conversation history
        may resolve references later, but it must never override a new self-contained
        topic.
        """

        lowered = current.casefold()

        source_terms = (
            "source", "sources", "cite", "citation", "citations",
            "verify", "verified", "look up", "lookup", "search the web",
            "search web", "research", "studies", "study", "find online",
            "evidence", "papers", "paper",
        )
        current_terms = (
            "right now", "currently", "current price", "today", "latest",
            "news", "weather", "forecast", "availability", "in stock",
            "market price", "price in", "how much does", "how much is",
            "find the price", "find price", "price of", "prices of",
        )
        action_terms = (
            "open ", "launch ", "create ", "delete ", "move ", "rename ",
            "click ", "type ", "paste ", "copy ", "download ", "upload ",
            "close ", "resize ", "write a file", "make a folder",
        )

        asks_sources = any(term in lowered for term in source_terms)
        asks_live = any(term in lowered for term in current_terms)
        asks_action = any(term in lowered for term in action_terms)
        comparison = any(
            term in lowered
            for term in (
                "compare",
                "comparison",
                " versus ",
                " vs ",
                "which is better",
            )
        )

        if comparison and (asks_sources or asks_live):
            return "hybrid"
        if asks_sources or asks_live or asks_action:
            return "tool"
        return "direct"


    async def _direct_answer(
        self,
        current: str,
        *,
        include_history: bool,
    ) -> str:
        history = []
        if include_history:
            context_text = self.session_memory.context_for(
                current, recent_turns=max(10, self.max_history_turns), relevant_older=10
            )
            if context_text:
                history.append(context_text)

        detailed = self._detailed_requested(current)
        style = (
            "The user explicitly asked for detail, so you may give a longer explanation, "
            "but still sound conversational rather than like a formal report."
            if detailed
            else
            "Default to a natural spoken-style answer: usually one to three short paragraphs. "
            "Give the conclusion first, then only the most useful reasons. Do not use headings, "
            "subheadings, numbered lists, bullet lists, tables, report sections, or long specification "
            "dumps unless the user explicitly asks for that format."
        )
        prompt = (
            "You are Conduit, a capable conversational AI assistant. Answer the "
            "user directly from the active model's general knowledge and reasoning. "
            "Do not pretend you performed a live web lookup or computer action. "
            "If the user asks for information that is clearly time-sensitive, say "
            "that a live lookup is needed instead of inventing current facts. "
            + style + " Do not fabricate sources or URLs.\n\n"
        )
        if history:
            prompt += "RECENT CONVERSATION:\n" + "\n".join(history) + "\n\n"
        prompt += "CURRENT USER MESSAGE:\n" + current

        response = await self.agent.loop.provider.chat(
            [ChatMessage(Role.USER, prompt)],
            model=self.agent.loop.model,
        )
        draft = response.text.strip()
        if not draft:
            return "I could not generate a direct answer."
        return await self._self_check_direct_answer(current, draft)

    async def _self_check_direct_answer(
        self,
        user_message: str,
        draft: str,
    ) -> str:
        """Second-pass consistency check using the active model itself."""

        prompt = (
            "You are Conduit's ANSWER CHECKER. Review the draft before it is spoken.\n"
            "Your job is NOT to guess corrections to uncertain facts. Detect internal "
            "contradictions, swapped specifications, impossible claims, and suspiciously "
            "precise technical details. Do not browse the web and do not invent sources. "
            "When an exact specification, benchmark, date, wattage, memory amount, bus width, "
            "clock, version, or other precise fact is not unquestionably stable to you, REMOVE "
            "the exact value rather than replacing it with another guess. Preserve qualitative "
            "conclusions only when you are confident in them. Preserve the user's requested level of "
            "detail. For a normal request, keep the final answer to one to three short paragraphs. "
            "If the user explicitly asked for detail, preserve that detail while still sounding conversational. "
            "Avoid headings, subheadings, tables, and report-like formatting unless detail was explicitly requested.\n\n"
            f"USER QUESTION:\n{user_message}\n\n"
            f"DRAFT ANSWER:\n{draft}\n\n"
            "Return only the corrected final answer."
        )
        try:
            checked = await self.agent.loop.provider.chat(
                [ChatMessage(Role.USER, prompt)],
                model=self.agent.loop.model,
            )
            answer = checked.text.strip()
            return answer or draft
        except Exception:
            return draft

    async def _compose_hybrid_answer(
        self,
        user_message: str,
        report: Any,
        *,
        search_plan: SearchPlan | None = None,
        evidence_hypothesis: str = "",
    ) -> str:
        """Combine model knowledge with live evidence instead of making either exclusive."""

        evidence = self._evidence_payload(report)
        web_observations = [
            item for item in evidence
            if item.get("success")
            and str(item.get("action", "")).startswith("web.")
        ]
        source_manifest = self._source_manifest(web_observations)
        source_manifest = await self._judge_source_relevance(
            user_message,
            source_manifest,
            search_plan=search_plan,
        )

        # A failed retrieval run must never be converted into a confident answer
        # merely because the preliminary model hypothesis exists.
        if not report.success:
            return self._failed_run_answer(report, web_observations)

        history = [
            {"user": turn.user, "assistant": turn.assistant}
            for turn in self.session_memory.recent_turns(3)
        ]

        style_instruction = self._conversation_style_instruction(
            user_message,
            search_plan=search_plan,
        )
        prompt = (
            "You are Conduit. Produce a natural conversational hybrid answer to the user's request.\n\n"
            + style_instruction + "\n\n"
            "Use THREE inputs correctly:\n"
            "0. PRELIMINARY MODEL HYPOTHESIS: this was generated before retrieval to "
            "identify likely claims/entities. It is NOT evidence and may be outdated.\n"
            "1. GENERAL MODEL KNOWLEDGE: You MAY use the active model's own stable "
            "knowledge for established specifications, concepts, technical comparisons, "
            "strengths, weaknesses, and general recommendations. Clearly distinguish "
            "this from live information when useful.\n"
            "2. LIVE WEB EVIDENCE: Use the supplied evidence for current prices, "
            "availability, news, weather, recent events, or whenever the user explicitly "
            "asked for sources. Cite retrieved sources as [S1], [S2], etc.\n\n"
            "Rules:\n"
            "- Never invent a current price, current availability, recent event, source, or URL.\n"
            "- A failed or incomplete web lookup does NOT prevent you from giving the "
            "full stable technical comparison from model knowledge.\n"
            "- If live evidence is missing, say exactly which live part could not be "
            "verified, then still answer the stable/general part fully.\n"
            "- If sources were requested, the final answer must actually answer the "
            "question; do not merely repeat search-result snippets or say that lookup completed.\n"
            "- If sources were requested, include only URLs from SOURCE MANIFEST.\n"
            "- For sourced rankings/statistics, retrieved evidence overrides model memory.\n"
            "- Do not describe model knowledge as live or verified web evidence.\n\n"
            f"RECENT CONVERSATION:\n{json.dumps(history, ensure_ascii=False)}\n\n"
            f"USER MESSAGE:\n{user_message}\n\n"
            f"PRELIMINARY MODEL HYPOTHESIS (UNVERIFIED):\n{evidence_hypothesis}\n\n"
            f"WEB RUN STATUS: {report.status.value}; success={report.success}\n"
            f"WEB FINAL MESSAGE: {report.final_message}\n\n"
            f"SOURCE MANIFEST:\n{json.dumps(source_manifest, ensure_ascii=False, indent=2)}\n\n"
            f"WEB EXECUTION EVIDENCE:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
        )

        response = await self.agent.loop.provider.chat(
            [ChatMessage(Role.USER, prompt)],
            model=self.agent.loop.model,
        )
        answer = response.text.strip()
        if answer:
            return answer
        return self._failed_run_answer(report, web_observations)


    def _conversation_web_actions(self, current: str) -> set[str]:
        """Select a generic web capability from the CURRENT request only."""

        lowered = current.casefold()

        explicit_browser_control = any(
            phrase in lowered
            for phrase in (
                "open the browser",
                "open browser",
                "navigate to",
                "click on",
                "fill the form",
                "use the browser on my screen",
                "show me in the browser",
            )
        ) and not any(
            phrase in lowered
            for phrase in (
                "don't open any browser",
                "do not open any browser",
                "without opening a browser",
                "no browser",
            )
        )
        if explicit_browser_control:
            return set()

        # Price has priority because a request may also say "compare current prices".
        if any(
            term in lowered
            for term in (
                "price",
                "cost",
                "how much",
                "market price",
                "price in",
                "prices in",
            )
        ):
            return {"web.price_search"}

        if any(
            term in lowered
            for term in (
                "news",
                "headlines",
                "latest update",
                "breaking",
            )
        ):
            return {"web.news"}

        if any(
            term in lowered
            for term in (
                "deep research",
                "research",
                "studies",
                "study",
                "papers",
                "evidence",
                "investigate",
                "detailed analysis",
            )
        ):
            return {"web.research"}

        if any(
            term in lowered
            for term in (
                "compare",
                "comparison",
                "versus",
                " vs ",
                "better value",
                "which one",
            )
        ):
            return {"web.compare"}

        if any(
            term in lowered
            for term in (
                "source",
                "sources",
                "cite",
                "citation",
                "verify",
                "look up",
                "lookup",
                "search web",
                "search the web",
                "find online",
                "current",
                "today",
                "right now",
                "weather",
                "forecast",
                "availability",
            )
        ):
            return {"web.search"}

        return set()

    def _goal_with_context(
        self,
        current: str,
        *,
        include_history: bool,
    ) -> str:
        base_rules = (
            "Respond to the CURRENT user request. Select generic Conduit capabilities "
            "from the current intent and derive all action arguments from the current "
            "request. Never reuse an old topic, product, location, or query unless the "
            "current request explicitly refers back to it. Use structured actions for "
            "live facts, sources, studies, prices, news, research, and computer work. "
            "For live-information requests, use web.* actions and do not open a visible "
            "browser unless explicitly requested. Do not ask for details already supplied."
        )

        if not include_history or not self.history:
            return (
                base_rules
                + "\n\nCURRENT USER REQUEST:\n"
                + current
            )

        history_lines: list[str] = []
        for turn in self.session_memory.recent_turns(2):
            history_lines.append(f"User: {turn.user}")
            history_lines.append(f"Conduit: {turn.assistant}")

        return (
            base_rules
            + "\n\nUse the recent conversation ONLY to resolve explicit references "
              "such as 'that', 'it', 'those', or 'which one'.\n\n"
            + "RECENT CONVERSATION:\n"
            + "\n".join(history_lines)
            + "\n\nCURRENT USER REQUEST:\n"
            + current
        )


    async def _compose_answer(
        self,
        user_message: str,
        report: Any,
        *,
        search_plan: SearchPlan | None = None,
        evidence_hypothesis: str = "",
    ) -> str:
        evidence = self._evidence_payload(report)
        web_observations = [
            item
            for item in evidence
            if item.get("success")
            and str(item.get("action", "")).startswith("web.")
        ]

        # Never turn a failed agent run into a confident factual answer.
        if not report.success:
            return self._failed_run_answer(report, web_observations)

        history = [
            {"user": turn.user, "assistant": turn.assistant}
            for turn in self.session_memory.recent_turns(3)
        ]
        source_manifest = self._source_manifest(web_observations)
        source_manifest = await self._judge_source_relevance(
            user_message,
            source_manifest,
            search_plan=search_plan,
        )
        quality_issue = self._web_quality_issue(web_observations)
        if quality_issue:
            return self._insufficient_web_answer(
                quality_issue,
                web_observations,
            )
        if not source_manifest and not any(
            str(item.get("data", {}).get("answer", "")).strip()
            for item in web_observations
        ):
            return self._insufficient_web_answer(
                "The retrieved results were not relevant enough to support the requested answer.",
                web_observations,
            )
        evidence_text = json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
        )

        style_instruction = self._conversation_style_instruction(
            user_message,
            search_plan=search_plan,
        )
        prompt = (
            "You are Conduit, an evidence-augmented conversational assistant. "
            "The model formed a preliminary hypothesis before retrieval. Use that as "
            "reasoning context, NOT as trusted evidence. The retrieved sources are the "
            "authority for claims the user asked to verify/source. Correct the hypothesis "
            "whenever retrieved evidence disagrees with it.\n\n"
            + style_instruction + "\n\n"
            "NON-NEGOTIABLE RULES:\n"
            "- You may use model knowledge to understand the question, connect evidence, "
            "and explain stable background, but never present an unsupported model-memory "
            "claim as verified by a source.\n"
            "- For the requested ranking/statistic/specification, only state a concrete "
            "verified value when the retrieved evidence supports it.\n"
            "- If the preliminary hypothesis conflicts with evidence, use the evidence.\n"
            "- Every sourced factual claim or paragraph must cite one or more "
            "source IDs such as [S1] or [S2].\n"
            "- A source ID may support only claims actually present in that source's "
            "title, snippet, price field, or grounded answer.\n"
            "- Do not infer missing specifications.\n"
            "- If evidence is mixed, incomplete, or irrelevant, clearly state that "
            "a reliable conclusion cannot yet be made.\n"
            "- For prices, state the market/region and warn that listings can change.\n"
            "- Do not claim a winner unless the evidence directly supports the user's "
            "criteria.\n"
            "- If sources were requested, end with one compact Sources line/paragraph mapping cited source IDs to URLs.\n\n"
            f"RECENT CONVERSATION:\n{json.dumps(history, ensure_ascii=False)}\n\n"
            f"USER MESSAGE:\n{user_message}\n\n"
            f"PRELIMINARY MODEL HYPOTHESIS (UNVERIFIED):\n{evidence_hypothesis}\n\n"
            f"SOURCE MANIFEST:\n{json.dumps(source_manifest, ensure_ascii=False, indent=2)}\n\n"
            f"STRUCTURED EXECUTION EVIDENCE:\n{evidence_text}"
        )

        try:
            response = await self.agent.loop.provider.chat(
                [ChatMessage(Role.USER, prompt)],
                model=self.agent.loop.model,
            )
            answer = response.text.strip()
            if answer and self._answer_is_grounded(
                answer,
                source_manifest,
                evidence_text,
            ):
                return answer
        except Exception:
            pass

        return self._grounded_fallback_answer(
            user_message,
            web_observations,
            source_manifest,
            report.final_message,
        )

    @staticmethod
    def _detailed_requested(current: str) -> bool:
        lowered = current.casefold()
        return any(
            term in lowered
            for term in (
                "detailed", "in detail", "full breakdown", "comprehensive",
                "exhaustive", "step by step", "write a report", "full report",
                "all specifications", "deep dive",
            )
        )

    def _conversation_style_instruction(
        self,
        current: str,
        *,
        search_plan: SearchPlan | None,
    ) -> str:
        detailed = self._detailed_requested(current) or (
            search_plan is not None and search_plan.answer_style == "detailed"
        )
        if detailed:
            return (
                "RESPONSE STYLE: The user asked for detail. Explain thoroughly but still "
                "sound like a helpful person speaking naturally. Use structure only when it "
                "meaningfully improves clarity; do not pad the answer."
            )
        return (
            "RESPONSE STYLE: Speak naturally like a human copilot whose answer may be read aloud. "
            "Start with the actual answer or conclusion and normally use one to three short "
            "paragraphs. Do not use headings, subheadings, numbered lists, bullet lists, tables, "
            "report sections, or labels such as 'Key Findings' or 'Conclusion' unless the user "
            "explicitly asks for that format. If sources were requested, answer conversationally "
            "first, then finish with one compact Sources line or short Sources paragraph; do not "
            "turn the answer into a source-by-source report."
        )

    async def _judge_source_relevance(
        self,
        user_message: str,
        source_manifest: dict[str, dict[str, Any]],
        *,
        search_plan: SearchPlan | None,
    ) -> dict[str, dict[str, Any]]:
        """Use the active model to discard semantically irrelevant search results."""

        if not source_manifest:
            return source_manifest

        prompt = (
            "You are Conduit's SEARCH RESULT RELEVANCE JUDGE. "
            "Select only sources that are genuinely about the CURRENT user's request. "
            "Reject same-word/different-meaning results, generic homepages that do not "
            "support the requested claim, wrong countries/markets, and unrelated entities. "
            "For research/studies prefer sources actually discussing the subject, especially "
            "academic, medical, official, journal, university, or review sources when relevant.\n\n"
            f"USER REQUEST:\n{user_message}\n\n"
            f"SEARCH PLAN:\n{json.dumps(search_plan.to_dict() if search_plan else {}, ensure_ascii=False)}\n\n"
            f"CANDIDATE SOURCES:\n{json.dumps(source_manifest, ensure_ascii=False, indent=2)}\n\n"
            'Return ONLY JSON: {"relevant_source_ids":["S1","S3"],'
            '"reason":"short explanation"}'
        )
        try:
            response = await self.agent.loop.provider.chat(
                [ChatMessage(Role.USER, prompt)],
                model=self.agent.loop.model,
            )
            raw = json.loads(response.text.strip().strip("`").replace("json\\n", "", 1))
            ids = raw.get("relevant_source_ids", [])
            if isinstance(ids, list):
                filtered = {
                    key: value
                    for key, value in source_manifest.items()
                    if key in {str(item) for item in ids}
                }
                if filtered:
                    return filtered
                return {}
        except Exception:
            pass
        return source_manifest

    @staticmethod
    def _failed_run_answer(
        report: Any,
        web_observations: list[dict[str, Any]],
    ) -> str:
        lines = [
            "I retrieved some information, but the agent run did not complete "
            f"successfully (`{report.status.value}`), so I cannot present a confident "
            "factual conclusion.",
        ]
        if report.final_message:
            lines.append(f"Reason: {report.final_message}")

        sources = ConversationSession._source_manifest(web_observations)
        if sources:
            lines.append("\nSources that were retrieved before the failure:")
            for source_id, source in sources.items():
                lines.append(
                    f"- [{source_id}] {source.get('title') or source.get('source')}: "
                    f"{source.get('url')}"
                )
        lines.append(
            "\nTry the request again or ask Conduit to continue researching. "
            "It will not fill missing facts from model memory."
        )
        return "\n".join(lines)

    @classmethod
    def _web_quality_issue(
        cls,
        web_observations: list[dict[str, Any]],
    ) -> str | None:
        if not web_observations:
            return None

        for item in web_observations:
            action = item.get("action")
            data = item.get("data", {})

            if action == "web.price_search":
                results = data.get("results", [])
                priced = [
                    result
                    for result in results
                    if result.get("price")
                ]
                if not priced:
                    return (
                        "No current listing with a parsed price was verified for "
                        "the requested product and market."
                    )

            elif action == "web.compare":
                comparison = (
                    data.get("metadata", {})
                    .get("comparison", {})
                )
                if len(comparison) < 2:
                    return "The comparison did not contain evidence for at least two items."
                weak = []
                for name, group in comparison.items():
                    evidence = group.get("evidence", [])
                    if len(evidence) < 2:
                        weak.append(name)
                if weak:
                    return (
                        "Insufficient relevant comparison evidence was retrieved for: "
                        + ", ".join(weak)
                        + "."
                    )

            elif action == "web.research":
                sources = data.get("sources", [])
                answer = str(data.get("answer", "")).strip()
                if not sources and not answer:
                    return "The research action returned no usable evidence."

        return None

    @staticmethod
    def _insufficient_web_answer(
        reason: str,
        web_observations: list[dict[str, Any]],
    ) -> str:
        lines = [
            "I could not verify enough reliable live evidence to answer confidently.",
            f"Reason: {reason}",
        ]
        sources = ConversationSession._source_manifest(web_observations)
        if sources:
            lines.append("\nRelevant sources found:")
            for source_id, source in sources.items():
                lines.append(
                    f"- [{source_id}] {source.get('title') or source.get('source')}: "
                    f"{source.get('url')}"
                )
        lines.append(
            "\nI have not filled the missing details from the model's internal knowledge."
        )
        return "\n".join(lines)

    @staticmethod
    def _source_manifest(
        web_observations: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        output: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        counter = 1

        for item in web_observations:
            data = item.get("data", {})
            candidates = []
            candidates.extend(data.get("results", []) or [])
            candidates.extend(data.get("sources", []) or [])

            comparison = data.get("metadata", {}).get("comparison", {})
            for group in comparison.values():
                candidates.extend(group.get("evidence", []) or [])
                candidates.extend(group.get("prices", []) or [])

            for source in candidates:
                if not isinstance(source, dict):
                    continue
                url = str(source.get("url", "")).strip()
                title = str(source.get("title", ""))
                snippet = str(source.get("snippet", ""))
                source_name = str(source.get("source", ""))
                presentation_text = f"{title} {snippet} {url} {source_name}".casefold()
                blocked_markers = (
                    "porn", "xxx", "adult video", "sex video", "pornhub",
                    "youporn", "redtube", "xvideos", "xnxx", "naughtyamerica",
                    "adulttime", "fullporner", "iporntv",
                )
                if any(marker in presentation_text for marker in blocked_markers):
                    continue
                if not url or url in seen:
                    continue
                seen.add(url)
                output[f"S{counter}"] = {
                    "title": title[:500],
                    "url": url,
                    "snippet": snippet[:1500],
                    "source": source_name[:200],
                    "price": source.get("price"),
                    "published_at": source.get("published_at"),
                }
                counter += 1
                if counter > 20:
                    return output
        return output

    @staticmethod
    def _answer_is_grounded(
        answer: str,
        source_manifest: dict[str, dict[str, Any]],
        evidence_text: str,
    ) -> bool:
        if not source_manifest:
            return False

        cited = set(re.findall(r"\[(S\d+)\]", answer))
        if not cited or not cited.issubset(source_manifest):
            return False

        # Reject substantial numeric claims that never appeared in retrieved evidence.
        evidence_numbers = set(
            re.findall(r"\b\d+(?:\.\d+)?\b", evidence_text)
        )
        answer_numbers = set(
            re.findall(r"\b\d+(?:\.\d+)?\b", answer)
        )
        harmless = {
            str(index)
            for index in range(1, 21)
        }
        unsupported = answer_numbers - evidence_numbers - harmless
        if unsupported:
            return False

        return True

    @staticmethod
    def _grounded_fallback_answer(
        user_message: str,
        web_observations: list[dict[str, Any]],
        source_manifest: dict[str, dict[str, Any]],
        final_message: str,
    ) -> str:
        lines = []
        if final_message:
            lines.append(final_message)

        for item in web_observations:
            action = item.get("action")
            data = item.get("data", {})

            if action in {"web.search", "web.news", "web.research"}:
                answer = str(data.get("answer", "")).strip()
                if answer:
                    lines.append("\n" + answer)
                else:
                    useful = data.get("results", []) or data.get("sources", [])
                    for result in useful[:5]:
                        source_id = next(
                            (
                                key for key, source in source_manifest.items()
                                if source.get("url") == result.get("url")
                            ),
                            None,
                        )
                        snippet = result.get("snippet") or result.get("title")
                        if snippet and source_id:
                            lines.append(f"- [{source_id}] {snippet}")

            elif action == "web.price_search":
                priced = [
                    result
                    for result in data.get("results", [])
                    if result.get("price")
                ]
                if priced:
                    lines.append("\nVerified listing observations:")
                    for result in priced[:6]:
                        source_id = next(
                            (
                                key
                                for key, source in source_manifest.items()
                                if source.get("url") == result.get("url")
                            ),
                            None,
                        )
                        tag = f"[{source_id}] " if source_id else ""
                        lines.append(
                            f"- {tag}{result.get('price')} — "
                            f"{result.get('title')}"
                        )

            elif action == "web.compare":
                comparison = data.get("metadata", {}).get("comparison", {})
                lines.append("\nRetrieved comparison evidence:")
                for name, group in comparison.items():
                    lines.append(f"\n{name}:")
                    for result in group.get("evidence", [])[:3]:
                        source_id = next(
                            (
                                key
                                for key, source in source_manifest.items()
                                if source.get("url") == result.get("url")
                            ),
                            None,
                        )
                        snippet = result.get("snippet") or result.get("title")
                        if snippet:
                            tag = f"[{source_id}] " if source_id else ""
                            lines.append(f"- {tag}{snippet}")

        if source_manifest:
            lines.append("\nSources:")
            for source_id, source in source_manifest.items():
                lines.append(
                    f"- [{source_id}] {source.get('title') or source.get('source')}: "
                    f"{source.get('url')}"
                )

        if not lines:
            return (
                "I could not produce a grounded answer because no usable live evidence "
                "was returned."
            )
        return "\n".join(lines)

    def _evidence_payload(self, report: Any) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        used = 0

        for observation in report.observations:
            item = {
                "action": observation.action,
                "success": observation.success,
                "message": observation.message,
                "arguments": self._safe_value(dict(observation.arguments)),
                "data": self._safe_value(dict(observation.data)),
                "error_type": observation.error_type,
            }
            encoded = json.dumps(item, ensure_ascii=False)
            if used + len(encoded) > self.max_observation_chars:
                payload.append(
                    {
                        "truncated": True,
                        "message": "Additional execution evidence was omitted due to size.",
                    }
                )
                break
            payload.append(item)
            used += len(encoded)

        return payload

    @classmethod
    def _safe_value(cls, value: Any, *, depth: int = 0) -> Any:
        if depth > 5:
            return "<nested data omitted>"
        if isinstance(value, dict):
            output: dict[str, Any] = {}
            for key, child in list(value.items())[:30]:
                output[str(key)] = cls._safe_value(child, depth=depth + 1)
            return output
        if isinstance(value, (list, tuple)):
            return [
                cls._safe_value(child, depth=depth + 1)
                for child in list(value)[:30]
            ]
        if isinstance(value, str):
            return value[:4_000]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)[:1_000]

    @staticmethod
    def _fallback_answer(report: Any, evidence: list[dict[str, Any]]) -> str:
        successful = [
            item for item in evidence
            if item.get("success") and item.get("action")
        ]
        if report.success:
            lines = [report.final_message or "The task completed successfully."]
            for item in successful[-4:]:
                lines.append(f"- {item['message']}")
            return "\n".join(lines)

        failures = [
            item for item in evidence
            if item.get("success") is False
        ]
        lines = [
            report.final_message
            or "I could not complete the request with enough verified evidence."
        ]
        for item in failures[-3:]:
            lines.append(f"- {item.get('action')}: {item.get('message')}")
        return "\n".join(lines)
