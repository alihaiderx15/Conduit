
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import re
from pathlib import Path
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal

from conduit.conversation import ConversationSession, normalize_conversation_command
from conduit.core.models import ChatMessage, Role
from conduit.core.errors import ProviderAuthenticationError, ProviderError, ProviderQuotaError
from conduit.providers.recovery import ProviderReplacement
from conduit.events import EventBus
from conduit.general_pc import GeneralPCAgent, GeneralPCAgentConfig
from conduit.memory import AgentMemoryBridge, MemoryManager, MemoryWriteMode
from conduit.providers.gemini import GeminiProvider
from conduit.providers.console_recovery import _choose_openai_model, _choose_grok_model
from conduit.providers.openai import OpenAIProvider
from conduit.providers.grok import GrokProvider
from conduit.providers.ollama import OllamaProvider
from conduit.speech_policy import speech_text_for_answer
from conduit.model_advisor import ollama_catalog, valid_ollama_model_name
from conduit.proactive import ProactiveContextBuilder, ProactiveTriggerEngine


class RuntimeSignals(QObject):
    ready = Signal(str, str)               # provider, model
    busy = Signal(bool)
    answer = Signal(str, str, bool)        # user, full chat answer, success
    speech = Signal(str)                    # future TTS-safe utterance
    console = Signal(str, str)             # level, message
    error = Signal(str)
    active_file = Signal(str, str)         # filename, kind
    provider_switched = Signal(str, str, str)   # provider, model, message
    provider_switch_failed = Signal(str, str)   # provider, message
    provider_recovery_needed = Signal(str, str, str, float)  # provider, kind, message, retry seconds
    ollama_models_ready = Signal(object)      # list[dict]
    ollama_models_failed = Signal(str)
    ollama_download_started = Signal(str)
    ollama_download_finished = Signal(str, bool, str)  # model, success, message
    stopped = Signal()


class _GuiLoggingHandler(logging.Handler):
    def __init__(self, signals: RuntimeSignals) -> None:
        super().__init__()
        self.signals = signals

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.signals.console.emit(
                record.levelname,
                self.format(record),
            )
        except Exception:
            pass


class ConduitGuiRuntime:
    """Own Conduit's asyncio agent loop on a dedicated background thread."""

    def __init__(
        self,
        *,
        provider_name: str,
        model: str,
        project_root: Path,
        no_memory: bool = False,
    ) -> None:
        self.provider_name = provider_name
        self.model = model
        self.project_root = Path(project_root)
        self.no_memory = bool(no_memory)

        self.signals = RuntimeSignals()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._active_task: asyncio.Task | None = None
        self._provider_recovery_future: asyncio.Future | None = None
        self._ollama_download_tasks: dict[str, asyncio.Task] = {}
        self._stop_requested = threading.Event()

        self.agent: GeneralPCAgent | None = None
        self.conversation: ConversationSession | None = None
        self.memory_manager: MemoryManager | None = None
        self.proactive_engine: ProactiveTriggerEngine | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._thread_main,
            name="Conduit-GUI-Runtime",
            daemon=True,
        )
        self._thread.start()

    def submit(self, text: str) -> None:
        command = text.strip()
        if not command:
            return
        self._enqueue(("ask", command))

    def register_dropped_file(self, path: str) -> None:
        self._enqueue(("file", path))

    def clear_history(self) -> None:
        self._enqueue(("clear", None))

    def list_actions(self) -> None:
        self._enqueue(("actions", None))

    def switch_provider(self, provider_name: str, api_key: str) -> None:
        """Validate credentials and hot-swap the active GUI reasoning provider."""
        provider = str(provider_name or "").casefold().strip()
        key = str(api_key or "").strip()
        if provider not in {"gemini", "openai", "grok"}:
            self.signals.provider_switch_failed.emit(provider or "provider", "Unsupported provider switch.")
            return
        if not key:
            self.signals.provider_switch_failed.emit(provider, "No API key was entered.")
            return
        self._enqueue(("provider_switch", {"provider": provider, "api_key": key}))

    def request_ollama_models(self) -> None:
        self._enqueue(("ollama_models", None))

    def switch_ollama_model(self, model: str) -> None:
        model = str(model or "").strip()
        if not valid_ollama_model_name(model):
            self.signals.ollama_models_failed.emit("Invalid Ollama model name.")
            return
        self._enqueue(("ollama_switch", {"model": model}))

    def ensure_ollama_model(self, model: str) -> None:
        """Switch to an installed model, otherwise download it visibly then switch."""
        model = str(model or "").strip()
        if not valid_ollama_model_name(model):
            self.signals.ollama_models_failed.emit("Invalid Ollama model name.")
            return
        self._enqueue(("ollama_ensure", {"model": model}))

    def download_ollama_model(self, model: str) -> None:
        model = str(model or "").strip()
        if not valid_ollama_model_name(model):
            self.signals.ollama_models_failed.emit("Invalid Ollama model name.")
            return
        self._enqueue(("ollama_download", {"model": model}))

    def resolve_provider_recovery(self, action: str, api_key: str = "") -> None:
        """Resume a provider-recovery prompt from the GUI thread."""
        loop = self._loop
        if loop is None:
            return

        def resolve() -> None:
            future = self._provider_recovery_future
            if future is not None and not future.done():
                future.set_result({
                    "action": str(action or "").casefold().strip(),
                    "api_key": str(api_key or "").strip(),
                })

        loop.call_soon_threadsafe(resolve)

    def interrupt(self) -> None:
        loop = self._loop
        if loop is None:
            return

        def cancel() -> None:
            if self._active_task is not None and not self._active_task.done():
                self._active_task.cancel()
            if self.conversation is not None:
                loop.create_task(self.conversation.interrupt())

        loop.call_soon_threadsafe(cancel)

    def stop(self) -> None:
        self._stop_requested.set()
        self._enqueue(("stop", None))

    def _enqueue(self, item: tuple[str, Any]) -> None:
        loop = self._loop
        queue = self._queue
        if loop is None or queue is None:
            self.signals.console.emit("WARN", "Conduit runtime is still starting.")
            return
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as exc:
            self.signals.error.emit(str(exc))
            self.signals.console.emit("ERROR", f"Runtime stopped unexpectedly: {exc}")
        finally:
            self.signals.stopped.emit()

    async def _provider(self):
        name = self.provider_name.casefold()
        if name == "ollama":
            return OllamaProvider()
        if name == "gemini":
            key = os.getenv("GEMINI_API_KEY", "").strip()
            if not key:
                raise RuntimeError(
                    "GEMINI_API_KEY is not set. Set it before starting the GUI."
                )
            return GeminiProvider(api_key=key)
        if name == "openai":
            key = os.getenv("OPENAI_API_KEY", "").strip()
            if not key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not set. Set it before starting the GUI."
                )
            return OpenAIProvider(api_key=key)
        if name == "grok":
            key = os.getenv("XAI_API_KEY", "").strip()
            if not key:
                raise RuntimeError(
                    "XAI_API_KEY is not set. Select Grok from Conduit's provider menu and enter your key."
                )
            return GrokProvider(api_key=key)
        raise RuntimeError(f"Unsupported provider: {self.provider_name}")

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        events = EventBus()

        def event_handler(event) -> None:
            payload = dict(event.payload)
            if self.conversation is not None:
                self.conversation.record_runtime_event(event.name, payload)
            line = self._format_event(event.name, payload)
            if line is not None:
                level, message = line
                self.signals.console.emit(level, message)

            if event.name == "agent.provider.switched":
                provider_name = str(payload.get("to_provider") or "").casefold().strip()
                model_name = str(payload.get("model") or "").strip()
                reason = str(payload.get("reason") or "")
                if provider_name and model_name:
                    self.provider_name = provider_name
                    self.model = model_name
                    # Manual button switches already emit provider_switched from
                    # _handle_provider_switch. Only automatic recovery needs a
                    # second UI notification here.
                    if "recovery" in reason.casefold() or "quota" in reason.casefold():
                        message = (
                            f"Recovered by switching to {provider_name.title()} using {model_name}. "
                            "The active task and file context were preserved."
                        )
                        self.signals.provider_switched.emit(provider_name, model_name, message)

        events.subscribe("*", event_handler)

        logging_handler = _GuiLoggingHandler(self.signals)
        logging_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(logging_handler)

        provider = await self._provider()

        memory_bridge = None
        if not self.no_memory:
            memory_path = self.project_root / "data" / "conduit-chat-memory.sqlite3"
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            self.memory_manager = MemoryManager(memory_path, event_bus=events)
            memory_bridge = AgentMemoryBridge(
                self.memory_manager,
                write_mode=MemoryWriteMode.AUTO_SAFE,
                event_bus=events,
            )

        try:
            self.signals.console.emit("INFO", "Loading Conduit modules...")
            self.agent = await GeneralPCAgent.create(
                provider=provider,
                model=self.model,
                config=GeneralPCAgentConfig(max_iterations=18),
                event_bus=events,
                memory_bridge=memory_bridge,
                provider_recovery_handler=self._gui_provider_recovery,
            )
            self.conversation = ConversationSession(self.agent, max_history_turns=12)
            self.proactive_engine = ProactiveTriggerEngine(
                ProactiveContextBuilder(self.memory_manager)
            )
            self.signals.ready.emit(self.provider_name, self.model)
            self.signals.console.emit(
                "INFO",
                f"Conduit system initialized. Provider={self.provider_name}, model={self.model}.",
            )

            if self.conversation.resume_context:
                compact = " ".join(self.conversation.resume_context.split())
                if len(compact) > 520:
                    compact = compact[:517] + "..."
                self._deliver_answer(
                    "",
                    "Welcome back. Previous session recap: " + compact,
                    True,
                )

            while not self._stop_requested.is_set():
                try:
                    kind, payload = await asyncio.wait_for(self._queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    if self.proactive_engine is not None and self.conversation is not None:
                        recent_topic = (
                            self.conversation.history[-1].user
                            if self.conversation.history else ""
                        )
                        suggestion = self.proactive_engine.evaluate(
                            session_turns=len(self.conversation.session_memory),
                            recent_topic=recent_topic,
                        )
                        if suggestion:
                            self.signals.console.emit("INFO", "proactive.triggered: " + suggestion)
                            self._deliver_answer("", suggestion, True)
                    continue
                if kind == "stop":
                    break
                if kind == "ask":
                    await self._handle_command(str(payload))
                elif kind == "file":
                    await self._handle_file(str(payload))
                elif kind == "clear":
                    self.conversation.clear()
                    self.signals.console.emit("INFO", "Conversation context cleared.")
                elif kind == "actions":
                    names = sorted(item.name for item in self.agent.actions.all())
                    self.signals.console.emit(
                        "INFO",
                        f"{len(names)} actions registered: " + ", ".join(names),
                    )
                elif kind == "provider_switch":
                    await self._handle_provider_switch(dict(payload or {}))
                elif kind == "ollama_models":
                    await self._handle_ollama_models()
                elif kind == "ollama_switch":
                    await self._handle_ollama_switch(str((payload or {}).get("model") or ""))
                elif kind == "ollama_ensure":
                    await self._handle_ollama_ensure(str((payload or {}).get("model") or ""))
                elif kind == "ollama_download":
                    await self._handle_ollama_download(str((payload or {}).get("model") or ""))
        finally:
            root_logger.removeHandler(logging_handler)
            if self.conversation is not None:
                try:
                    summary = self.conversation.finalize_session()
                    if summary:
                        self.signals.console.emit("INFO", "Session recap saved for next launch.")
                except Exception as exc:
                    self.signals.console.emit("WARN", f"Session recap could not be saved: {exc}")
            if self.agent is not None:
                await self.agent.close()
            if self.memory_manager is not None:
                self.memory_manager.close()
            self.agent = None
            self.conversation = None

    async def _handle_ollama_models(self) -> None:
        provider = OllamaProvider()
        try:
            models = await provider.list_models()
            self.signals.ollama_models_ready.emit(ollama_catalog(models))
        except Exception as exc:
            message = f"Could not list Ollama models: {exc}"
            self.signals.console.emit("ERROR", message)
            self.signals.ollama_models_failed.emit(message)
        finally:
            await provider.close()

    async def _handle_ollama_switch(self, model: str) -> None:
        model = str(model or "").strip()
        if not valid_ollama_model_name(model):
            self.signals.ollama_models_failed.emit("Invalid Ollama model name.")
            return

        candidate = OllamaProvider()
        switched = False
        self.signals.busy.emit(True)
        try:
            installed = await candidate.list_models()
            match = next((item for item in installed if item.casefold() == model.casefold()), None)
            if match is None:
                raise RuntimeError(
                    f"Ollama model '{model}' is not installed. Download it first."
                )
            await candidate.model_capabilities(match)
            await self.agent.switch_provider(
                candidate,
                match,
                reason=f"User selected Ollama model {match} from the GUI.",
            )
            switched = True
            self.provider_name = "ollama"
            self.model = match
            message = (
                f"Switched to Ollama model {match}. "
                "Conversation history and the active file were preserved."
            )
            self.signals.console.emit("INFO", message)
            self.signals.provider_switched.emit("ollama", match, message)
        except Exception as exc:
            if not switched:
                try:
                    await candidate.close()
                except Exception:
                    pass
            message = f"Ollama model switch failed: {exc}"
            self.signals.console.emit("ERROR", message)
            self.signals.ollama_models_failed.emit(message)
        finally:
            self.signals.busy.emit(False)

    async def _handle_ollama_ensure(self, model: str) -> None:
        provider = OllamaProvider()
        try:
            installed = await provider.list_models()
        except Exception as exc:
            await provider.close()
            self.signals.ollama_models_failed.emit(f"Could not check Ollama models: {exc}")
            return
        await provider.close()

        if any(item.casefold() == model.casefold() for item in installed):
            await self._handle_ollama_switch(model)
            return
        await self._handle_ollama_download(model)

    async def _handle_ollama_download(self, model: str) -> None:
        """Start an Ollama pull in a visible CMD and return immediately.

        Large models can take many minutes to download. The GUI/runtime must
        remain usable while the external Ollama process continues in parallel.
        """
        model = str(model or "").strip()
        if not valid_ollama_model_name(model):
            self.signals.ollama_models_failed.emit("Invalid Ollama model name.")
            return
        if os.name != "nt":
            self.signals.ollama_models_failed.emit(
                "Automatic visible Ollama downloads are currently implemented for Windows."
            )
            return

        existing = self._ollama_download_tasks.get(model.casefold())
        if existing is not None and not existing.done():
            self.signals.console.emit(
                "INFO",
                f"Ollama model {model} is already downloading in the background.",
            )
            self.signals.ollama_download_started.emit(model)
            return

        try:
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            process = subprocess.Popen(
                ["cmd.exe", "/c", "ollama", "pull", model],
                shell=False,
                creationflags=creationflags,
            )
        except Exception as exc:
            message = f"Could not start Ollama model download {model}: {exc}"
            self.signals.console.emit("ERROR", message)
            self.signals.ollama_download_finished.emit(model, False, message)
            return

        self.signals.ollama_download_started.emit(model)
        self.signals.console.emit(
            "INFO",
            f"Background download started in Command Prompt: ollama pull {model}. "
            "Conduit remains available while it downloads.",
        )

        task = asyncio.create_task(
            self._watch_ollama_download(model, process),
            name=f"ollama-pull:{model}",
        )
        self._ollama_download_tasks[model.casefold()] = task

    async def _watch_ollama_download(self, model: str, process) -> None:
        key = model.casefold()
        try:
            exit_code = await asyncio.to_thread(process.wait)
            if exit_code != 0:
                raise RuntimeError(f"ollama pull exited with code {exit_code}.")
            message = (
                f"Downloaded Ollama model {model}. It is now available in the Ollama model selector."
            )
            self.signals.console.emit("INFO", message)
            self.signals.ollama_download_finished.emit(model, True, message)
        except Exception as exc:
            message = f"Could not download Ollama model {model}: {exc}"
            self.signals.console.emit("ERROR", message)
            self.signals.ollama_download_finished.emit(model, False, message)
        finally:
            self._ollama_download_tasks.pop(key, None)


    @staticmethod
    def _retry_after_seconds(message: str) -> float:
        match = re.search(r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)\s*s", message, re.I)
        if match:
            return max(1.0, float(match.group(1)))
        match = re.search(r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)\s*seconds?", message, re.I)
        if match:
            return max(1.0, float(match.group(1)))
        return 0.0

    async def _validated_recovery_provider(self, provider_name: str, api_key: str):
        provider_name = provider_name.casefold().strip()
        candidate = None
        try:
            if provider_name == "gemini":
                candidate = GeminiProvider(api_key=api_key)
                models = await candidate.list_models()
                model = self._choose_gemini_model(models, "")
                if not model:
                    raise RuntimeError("No usable Gemini model was available to this API key.")
            elif provider_name == "openai":
                candidate = OpenAIProvider(api_key=api_key)
                models = await candidate.list_models()
                model = _choose_openai_model(models)
                if not model:
                    raise RuntimeError("No usable OpenAI model was available to this API key.")
            elif provider_name == "grok":
                candidate = GrokProvider(api_key=api_key)
                models = await candidate.list_models()
                model = _choose_grok_model(models)
                if not model:
                    raise RuntimeError("No usable Grok model was available to this xAI API key.")
            elif provider_name == "ollama":
                candidate = OllamaProvider()
                models = await candidate.list_models()
                if not models:
                    raise RuntimeError("Ollama is running but no local models are installed.")
                preferred = self.model if self.model in models else ""
                model = preferred or next(
                    (m for m in models if "qwen" in m.casefold()),
                    models[0],
                )
                return candidate, model
            else:
                raise RuntimeError(f"Unsupported provider recovery target: {provider_name}")

            validation = await candidate.chat(
                [ChatMessage(Role.USER, "Reply with OK only.")],
                model=model,
            )
            if not validation.text.strip():
                raise RuntimeError(f"{provider_name.title()} returned an empty validation response.")
            return candidate, model
        except Exception:
            if candidate is not None:
                try:
                    await candidate.close()
                except Exception:
                    pass
            raise

    async def _gui_provider_recovery(self, error: ProviderError, current, current_model: str):
        """GUI equivalent of the console provider-recovery workflow.

        The current task remains paused while the GUI asks for another key,
        another provider/model, a timed retry, or cancellation.
        """
        provider_id = str(getattr(current, "provider_id", self.provider_name) or self.provider_name)
        original_kind = (
            "quota" if isinstance(error, ProviderQuotaError)
            else "authentication" if isinstance(error, ProviderAuthenticationError)
            else "provider"
        )
        retry_seconds = self._retry_after_seconds(str(error)) if isinstance(error, ProviderQuotaError) else 0.0
        detail = str(error)

        while True:
            loop = asyncio.get_running_loop()
            self._provider_recovery_future = loop.create_future()
            self.signals.console.emit(
                "WARN",
                f"{provider_id.title()} {original_kind} issue detected. Task paused for provider recovery.",
            )
            self.signals.provider_recovery_needed.emit(
                provider_id,
                original_kind,
                detail,
                float(retry_seconds),
            )

            try:
                choice = await self._provider_recovery_future
            finally:
                self._provider_recovery_future = None

            action = str((choice or {}).get("action") or "").casefold().strip()
            api_key = str((choice or {}).get("api_key") or "").strip()

            if action == "cancel" or not action:
                return None

            if action == "wait":
                delay = retry_seconds or 45.0
                self.signals.console.emit(
                    "INFO",
                    f"Waiting {delay:.0f} seconds before retrying {provider_id.title()}...",
                )
                await asyncio.sleep(delay)
                return ProviderReplacement(
                    current,
                    current_model,
                    "User waited for provider quota and retried.",
                )

            if action == "alternate_model":
                try:
                    models = await current.list_models()
                    alternatives = [m for m in models if m != current_model]
                    if not alternatives:
                        raise RuntimeError("No alternate model is available for this provider.")
                    if provider_id == "gemini":
                        flash = [m for m in alternatives if "flash" in m.casefold()]
                        model = flash[0] if flash else alternatives[0]
                    elif provider_id == "openai":
                        model = _choose_openai_model(alternatives)
                        if not model:
                            model = alternatives[0]
                    elif provider_id == "grok":
                        model = _choose_grok_model(alternatives)
                        if not model:
                            model = alternatives[0]
                    else:
                        model = alternatives[0]
                    return ProviderReplacement(
                        current,
                        model,
                        f"GUI recovery selected alternate {provider_id.title()} model {model}.",
                    )
                except Exception as exc:
                    detail = f"Could not switch models: {exc}"
                    self.signals.console.emit("ERROR", detail)
                    continue

            if action in {"gemini", "openai", "grok"}:
                try:
                    if not api_key:
                        raise RuntimeError(f"No {action.title()} API key was provided.")
                    candidate, model = await self._validated_recovery_provider(action, api_key)
                    if action == "gemini":
                        os.environ["GEMINI_API_KEY"] = api_key
                        os.environ["CONDUIT_GEMINI_SEARCH_MODEL"] = model
                    elif action == "openai":
                        os.environ["OPENAI_API_KEY"] = api_key
                    else:
                        os.environ["XAI_API_KEY"] = api_key
                    return ProviderReplacement(
                        candidate,
                        model,
                        f"GUI recovery switched to {action.title()} after {original_kind} failure.",
                    )
                except Exception as exc:
                    detail = f"{action.title()} validation failed: {exc}"
                    self.signals.console.emit("ERROR", detail)
                    continue

            if action == "ollama":
                try:
                    candidate, model = await self._validated_recovery_provider("ollama", "")
                    return ProviderReplacement(
                        candidate,
                        model,
                        f"GUI recovery switched to Ollama after {original_kind} failure.",
                    )
                except Exception as exc:
                    detail = f"Ollama recovery failed: {exc}"
                    self.signals.console.emit("ERROR", detail)
                    continue

            detail = "Unknown provider recovery option."

    @staticmethod
    def _choose_gemini_model(models: list[str], current_model: str = "") -> str:
        """Use the same automatic Gemini model-selection policy as the console shell."""
        if not models:
            return ""
        preferred = "gemini-flash-latest"
        if preferred in models:
            return preferred
        if current_model in models and "gemini" in current_model.casefold():
            return current_model
        flash_models = [m for m in models if "flash" in m.casefold()]
        return flash_models[0] if flash_models else models[0]

    async def _handle_provider_switch(self, payload: dict[str, Any]) -> None:
        if self.agent is None or self.conversation is None:
            self.signals.provider_switch_failed.emit(
                str(payload.get("provider") or "provider"),
                "Conduit is not ready yet.",
            )
            return

        provider_name = str(payload.get("provider") or "").casefold().strip()
        api_key = str(payload.get("api_key") or "").strip()
        if provider_name not in {"gemini", "openai", "grok"}:
            self.signals.provider_switch_failed.emit(provider_name or "provider", "Unsupported provider switch.")
            return
        if not api_key:
            self.signals.provider_switch_failed.emit(provider_name, "No API key was entered.")
            return

        self.signals.busy.emit(True)
        self.signals.console.emit("INFO", f"Connecting to {provider_name.title()} and discovering available models...")
        candidate = None
        switched = False
        try:
            if provider_name == "gemini":
                candidate = GeminiProvider(api_key=api_key)
                models = await candidate.list_models()
                chosen_model = self._choose_gemini_model(models, self.model)
                if not chosen_model:
                    raise RuntimeError("No usable Gemini model was available to this API key.")
            elif provider_name == "openai":
                candidate = OpenAIProvider(api_key=api_key)
                models = await candidate.list_models()
                chosen_model = _choose_openai_model(models)
                if not chosen_model:
                    raise RuntimeError("No usable OpenAI GPT model was available to this API key.")
            else:
                candidate = GrokProvider(api_key=api_key)
                models = await candidate.list_models()
                chosen_model = _choose_grok_model(models)
                if not chosen_model:
                    raise RuntimeError("No usable Grok language model was available to this xAI API key.")

            validation = await candidate.chat(
                [ChatMessage(Role.USER, "Reply with OK only.")],
                model=chosen_model,
            )
            if not validation.text.strip():
                raise RuntimeError(f"{provider_name.title()} returned an empty validation response.")

            await self.agent.switch_provider(
                candidate,
                chosen_model,
                reason=f"User switched the GUI reasoning provider to {provider_name.title()}.",
            )
            switched = True
            self.provider_name = provider_name
            self.model = chosen_model
            if provider_name == "gemini":
                os.environ["GEMINI_API_KEY"] = api_key
                os.environ["CONDUIT_GEMINI_SEARCH_MODEL"] = chosen_model
            elif provider_name == "openai":
                os.environ["OPENAI_API_KEY"] = api_key
            else:
                os.environ["XAI_API_KEY"] = api_key

            message = (
                f"Connected to {provider_name.title()} using {chosen_model}. "
                "Conversation history and the active file were preserved."
            )
            self.signals.console.emit("INFO", message)
            self.signals.provider_switched.emit(provider_name, chosen_model, message)
        except Exception as exc:
            if candidate is not None and not switched:
                try:
                    await candidate.close()
                except Exception:
                    pass
            message = f"{provider_name.title()} connection failed: {exc}"
            self.signals.console.emit("ERROR", message)
            self.signals.provider_switch_failed.emit(provider_name, message)
        finally:
            self.signals.busy.emit(False)

    def _deliver_answer(self, user: str, answer: str, success: bool) -> None:
        """Keep the full answer in chat while limiting future spoken output."""
        self.signals.answer.emit(user, answer, success)
        speech = speech_text_for_answer(answer, max_words=50)
        if speech:
            self.signals.speech.emit(speech)

    def _finish_direct_command(self, user: str, answer: str, success: bool = True) -> None:
        """Deliver a synchronous conversation command and restore GUI input."""
        self._deliver_answer(user, answer, success)
        self.signals.busy.emit(False)

    async def _handle_command(self, command: str) -> None:
        if self.conversation is None:
            self.signals.error.emit("Conduit is not ready yet.")
            return

        normalized_command = normalize_conversation_command(command)
        lowered = normalized_command.casefold().strip()
        if self.proactive_engine is not None:
            self.proactive_engine.mark_user_activity()

        if lowered == "/clear":
            self.conversation.clear()
            self._finish_direct_command(command, "Conversation context cleared.", True)
            return

        if lowered == "/history":
            if not self.conversation.history:
                answer = "No conversation turns yet."
            else:
                answer = "\n\n".join(
                    f"{i}. You: {turn.user}\nConduit: {turn.assistant}"
                    for i, turn in enumerate(self.conversation.history, start=1)
                )
            self._finish_direct_command(command, answer, True)
            return

        if lowered == "/actions":
            names = sorted(item.name for item in self.agent.actions.all())
            self._finish_direct_command(
                command,
                f"{len(names)} registered actions:\n" + "\n".join(names),
                True,
            )
            return

        if lowered == "/provider":
            provider = str(getattr(self.agent.loop.provider, "provider_id", self.provider_name))
            model = str(getattr(self.agent.loop, "model", self.model))
            self._finish_direct_command(command, f"Current provider: {provider}. Model: {model}.", True)
            return

        # Preserve the existing WhatsApp/Discord send-confirmation workflow.
        if self.conversation._messaging_context.get("pending_message"):
            if lowered in {"yes", "y", "send", "send it", "confirm"}:
                self.signals.busy.emit(True)
                try:
                    answer, report = await self.conversation.confirm_pending_message(True)
                    self._deliver_answer(command, answer, bool(report.success))
                finally:
                    self.signals.busy.emit(False)
                return
            if lowered in {"no", "n", "cancel", "don't send", "do not send"}:
                self.signals.busy.emit(True)
                try:
                    answer, report = await self.conversation.confirm_pending_message(False)
                    self._deliver_answer(command, answer, bool(report.success))
                finally:
                    self.signals.busy.emit(False)
                return
            self._deliver_answer(
                command,
                "A message is waiting for confirmation. Type YES to send it or NO to cancel it.",
                False,
            )
            return

        self.signals.busy.emit(True)

        # Keep a copyable transcript in the programmer console as well as the
        # normal right-side chat. The GUI already renders the user's prompt in
        # ChatView immediately; this USER line is only for debugging/log export.
        self.signals.console.emit("USER", command)

        try:
            self._active_task = asyncio.create_task(self.conversation.ask(command))
            answer, report = await self._active_task
            success = bool(getattr(report, "success", True))
            self._deliver_answer(command, answer, success)
            status = getattr(getattr(report, "status", None), "value", "unknown")
            self.signals.console.emit(
                "INFO" if success else "WARN",
                f"Turn completed: status={status}, iterations={getattr(report, 'iterations', 0)}.",
            )
        except asyncio.CancelledError:
            await self.conversation.interrupt()
            self._deliver_answer(command, "Interrupted. I'm listening.", False)
            self.signals.console.emit("WARN", "Active task interrupted by user.")
        except Exception as exc:
            self._deliver_answer(
                command,
                f"I could not process that request: {exc}",
                False,
            )
            self.signals.console.emit("ERROR", f"{type(exc).__name__}: {exc}")
        finally:
            self._active_task = None
            self.signals.busy.emit(False)

    async def _handle_file(self, path: str) -> None:
        if self.conversation is None:
            self.signals.error.emit("Conduit is not ready yet.")
            return
        try:
            item = self.conversation.register_gui_dropped_file(path)
            self.signals.active_file.emit(item.original_name, item.kind.value)
            self.signals.console.emit(
                "INFO",
                f"GUI file loaded: {item.original_name} ({item.kind.value}) from {item.path}",
            )
        except Exception as exc:
            self.signals.error.emit(str(exc))
            self.signals.console.emit("ERROR", f"File drop failed: {exc}")

    @staticmethod
    def _format_event(name: str, payload: dict[str, Any]) -> tuple[str, str] | None:
        if name == "agent.decision.made":
            action = payload.get("action")
            reason = str(payload.get("reason", "")).strip()
            return "INFO", f"Agent selected {action}" + (f" — {reason}" if reason else "")
        if name in {"tool.started", "execution.started"}:
            tool = payload.get("tool_name") or payload.get("action") or payload.get("name")
            return "INFO", f"Executing {tool or name}..."
        if name in {"tool.completed", "execution.completed"}:
            tool = payload.get("tool_name") or payload.get("action") or payload.get("name")
            ok = payload.get("success", True)
            return ("INFO" if ok else "WARN"), f"{tool or name} completed (success={ok})."
        if "error" in name or "failed" in name:
            return "ERROR", f"{name}: {json.dumps(payload, default=str)[:1000]}"
        if name.startswith("messaging."):
            stage = payload.get("stage") or payload.get("state") or payload.get("detail")
            if stage:
                return "INFO", f"{payload.get('service','messaging')}: {stage}"
            return None
        if name.startswith("memory."):
            if name.endswith(("retrieved", "written", "proposed")):
                return "INFO", f"{name}: {json.dumps(payload, default=str)[:700]}"
            return None
        if name.startswith(("file.", "code.", "conversation.", "browser.", "system.")):
            return "INFO", f"{name}: {json.dumps(payload, default=str)[:900]}"
        return None
