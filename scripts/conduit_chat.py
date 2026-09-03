r"""Interactive natural-language Conduit shell.

Examples:
    py scripts\conduit_chat.py ollama --model qwen3:8b
    py scripts\conduit_chat.py gemini --model gemini-flash-latest
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
from pathlib import Path

from conduit.conversation import ConversationSession
from conduit.conversation import normalize_conversation_command
from conduit.events import EventBus
from conduit.general_pc import GeneralPCAgent, GeneralPCAgentConfig
from conduit.memory import AgentMemoryBridge, MemoryManager, MemoryWriteMode
from conduit.providers.console_recovery import ConsoleProviderRecovery
from conduit.providers.gemini import GeminiProvider
from conduit.providers.openai import OpenAIProvider
from conduit.providers.console_input import masked_input
from conduit.providers.console_recovery import _choose_openai_model, _select_ollama_model
from conduit.core.models import ChatMessage, Role
from conduit.providers.ollama import OllamaProvider


def _detect_provider_switch(text: str) -> str | None:
    """Detect clear natural-language provider switching commands, typo-tolerantly."""
    import re

    lowered = " ".join(text.casefold().split())
    if not lowered:
        return None

    targets = {
        "gemini": ("gemini",),
        "ollama": ("ollama",),
        "openai": ("openai", "open ai"),
    }
    verbs = ("switch", "use", "change", "connect", "go", "move")

    # Require a switching verb (or /switch command) so ordinary questions such
    # as "what is OpenAI?" do not trigger a provider change.
    has_switch_intent = lowered.startswith("/switch") or any(
        re.search(rf"\b{re.escape(verb)}\b", lowered)
        for verb in verbs
    )
    if not has_switch_intent:
        return None

    for provider, names in targets.items():
        if any(name in lowered for name in names):
            return provider
    return None


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("gemini", "ollama", "openai"))
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--show-events",
        action="store_true",
        help="Show detailed agent events instead of compact progress.",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Disable persistent memory retrieval for this chat session.",
    )
    args = parser.parse_args()

    if args.provider == "gemini":
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            key = await asyncio.to_thread(masked_input, "Gemini API key: ")
        provider = GeminiProvider(api_key=key)
    elif args.provider == "openai":
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            key = await asyncio.to_thread(masked_input, "OpenAI API key: ")
        provider = OpenAIProvider(api_key=key)
        if args.model.casefold() == "auto":
            args.model = _choose_openai_model(await provider.list_models())
            if not args.model:
                raise SystemExit("No usable OpenAI model was available to this API key.")
    else:
        provider = OllamaProvider()

    project_root = Path(__file__).resolve().parents[1]
    events = EventBus()
    memory_manager: MemoryManager | None = None
    memory_bridge = None

    if not args.no_memory:
        memory_path = project_root / "data" / "conduit-chat-memory.sqlite3"
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_manager = MemoryManager(memory_path, event_bus=events)
        memory_bridge = AgentMemoryBridge(
            memory_manager,
            write_mode=MemoryWriteMode.PROPOSE_ONLY,
            event_bus=events,
        )

    state = {
        "last_action": None,
        "active_task": None,
        "interrupt_requested": False,
        "last_messaging_state": None,
    }

    async def display_event(event) -> None:
        payload = dict(event.payload)

        if args.show_events:
            if event.name.startswith(
                (
                    "agent.",
                    "general_pc.",
                    "execution.",
                    "tool.",
                    "memory.",
                    "conversation.",
                )
            ):
                print(f"\n[event] {event.name}: {payload}")
            return

        if event.name == "conversation.search.planned":
            rewritten = str(payload.get("rewritten_request", "")).strip()
            if rewritten:
                print(f"\nConduit understood the search as: {rewritten}")

        elif event.name == "agent.decision.made":
            action = payload.get("action")
            if action and action != state["last_action"]:
                reason = str(payload.get("reason", "")).strip()
                print(f"\nConduit is using {action}...")
                if reason:
                    print(f"  {reason}")
                state["last_action"] = action

        elif event.name == "agent.provider.recovery.required":
            print("\nThe active AI provider became unavailable; recovery is starting.")

        elif event.name == "agent.provider.switched":
            print(
                "\nProvider switched to "
                f"{payload.get('to_provider')} / {payload.get('model')}."
            )

        elif event.name == "agent.action.guided":
            print(
                "\nConduit corrected the next action to "
                f"{payload.get('guided_action')}."
            )

        elif event.name == "messaging.client.state":
            state_name = str(payload.get("state", "")).strip()
            if state_name and state_name != state.get("last_messaging_state"):
                if state_name in {"loading", "unknown"}:
                    print(f"\nConduit is waiting for {str(payload.get('service', '')).title()} to become ready...")
                elif state_name == "ready":
                    print(f"\n{str(payload.get('service', '')).title()} is ready.")
                state["last_messaging_state"] = state_name

        elif event.name == "messaging.stage":
            service_key = str(payload.get("service", "")).casefold().strip()
            service_name = service_key.title()
            detail = str(payload.get("detail", "")).strip()
            stage_key = str(payload.get("stage", "")).casefold().strip()
            stage = stage_key.replace("_", " ")

            # Discord emits detailed internal stages for diagnostics, but the
            # normal console only needs the checkpoints that help a user locate
            # a failure without narrating every focus/readiness sub-step.
            if service_key == "discord":
                visible_discord_stages = {
                    "client_opened",
                    "dm_navigation",
                    "recipient_search",
                    "open_matching_result",
                    "chat_verified",
                }
                if stage_key not in visible_discord_stages:
                    return
                concise = {
                    "client_opened": "Discord is open.",
                    "dm_navigation": "Opening Direct Messages.",
                    "chat_verified": "Discord chat verified.",
                }.get(stage_key, detail)
                if concise:
                    print(f"\n[Discord] {concise}")
                return

            if detail:
                print(f"\n[{service_name} messaging] {detail}")
            elif stage:
                print(f"\n[{service_name} messaging] {stage}")

        elif event.name == "messaging.focus.recovery":
            service_name = str(payload.get("service", "")).title()
            attempt = payload.get("attempt")
            maximum = payload.get("max_attempts")
            print(
                f"\nConduit is restoring focus to {service_name} "
                f"(attempt {attempt}/{maximum})..."
            )

        elif event.name == "agent.decision_recovery":
            print("\nConduit is correcting an invalid model instruction.")

    events.subscribe("*", display_event)

    recovery = ConsoleProviderRecovery(
        ollama_model="qwen3:8b",
        gemini_model=(
            args.model
            if args.provider == "gemini"
            else "gemini-flash-latest"
        ),
    )

    agent = await GeneralPCAgent.create(
        provider=provider,
        model=args.model,
        config=GeneralPCAgentConfig(max_iterations=18),
        event_bus=events,
        memory_bridge=memory_bridge,
        provider_recovery_handler=recovery,
    )
    conversation = ConversationSession(agent)

    print("\nCONDUIT CONVERSATIONAL SHELL")
    print(f"Provider: {args.provider} | Model: {args.model}")
    print("Type normal English requests.")
    print(
        "Commands: /clear, /actions, /history, /provider, "
        "/switch gemini, /switch ollama, /switch openai, /exit"
    )
    print(
        "\nExample: Find the current price of an RTX 3070 Ti "
        "in the Pakistani market and show the sources."
    )

    async def switch_to_gemini() -> bool:
        print("\nSwitching to Gemini online mode.")
        key = await asyncio.to_thread(masked_input, "Enter Gemini API key: ")
        key = key.strip()
        if not key:
            print("Conduit: No API key was entered.")
            return False

        candidate = GeminiProvider(api_key=key)
        try:
            models = await candidate.list_models()
            preferred = "gemini-flash-latest"
            if preferred in models:
                chosen_model = preferred
            elif args.model in models and "gemini" in args.model.casefold():
                chosen_model = args.model
            else:
                flash_models = [
                    model
                    for model in models
                    if "flash" in model.casefold()
                ]
                chosen_model = (
                    flash_models[0]
                    if flash_models
                    else (models[0] if models else preferred)
                )

            validation = await candidate.chat(
                [ChatMessage(Role.USER, "Reply with OK only.")],
                model=chosen_model,
            )
            if not validation.text.strip():
                raise RuntimeError(
                    "Gemini returned an empty validation response."
                )

            os.environ["GEMINI_API_KEY"] = key
            os.environ["CONDUIT_GEMINI_SEARCH_MODEL"] = chosen_model
            await agent.switch_provider(
                candidate,
                chosen_model,
                reason="User switched the conversation to Gemini online mode.",
            )
            print(
                f"Conduit: Connected to Gemini using {chosen_model}. "
                "Conversation history was preserved."
            )
            return True
        except Exception as exc:
            await candidate.close()
            print(f"Conduit: Gemini validation failed: {exc}")
            return False

    async def switch_to_ollama() -> bool:
        print("\nSwitching to Ollama local mode.")
        candidate = OllamaProvider()
        try:
            chosen_model = await _select_ollama_model(candidate)
            await candidate.model_capabilities(chosen_model)
            await agent.switch_provider(
                candidate,
                chosen_model,
                reason="User selected an installed Ollama model.",
            )
            print(
                f"Conduit: Connected to Ollama using {chosen_model}. "
                "Conversation history was preserved."
            )
            return True
        except Exception as exc:
            await candidate.close()
            print(f"Conduit: Ollama validation failed: {exc}")
            return False

    async def switch_to_openai() -> bool:
        print("\nSwitching to OpenAI online mode.")
        key = await asyncio.to_thread(masked_input, "Enter OpenAI API key: ")
        key = key.strip()
        if not key:
            print("Conduit: No API key was entered.")
            return False
        candidate = OpenAIProvider(key)
        try:
            models = await candidate.list_models()
            chosen_model = _choose_openai_model(models)
            if not chosen_model:
                raise RuntimeError("No usable OpenAI GPT model was available to this API key.")
            await candidate.chat(
                [ChatMessage(Role.USER, "Reply with OK only.")],
                model=chosen_model,
            )
            os.environ["OPENAI_API_KEY"] = key
            await agent.switch_provider(
                candidate,
                chosen_model,
                reason="User switched the conversation to OpenAI.",
            )
            print(
                f"Conduit: Connected to OpenAI using {chosen_model}. "
                "Conversation history was preserved."
            )
            return True
        except Exception as exc:
            await candidate.close()
            print(f"Conduit: OpenAI validation failed: {exc}")
            return False

    def provider_status() -> None:
        capabilities = agent.loop.provider.capabilities
        print(
            "Conduit: Active provider is "
            f"{agent.loop.provider.provider_id} / {agent.loop.model}."
        )
        print(
            "Transport capabilities: "
            f"chat={capabilities.chat}, tools={capabilities.tools}, "
            f"vision={capabilities.vision}."
        )
        print(f"Conversation turns preserved: {len(conversation.history)}")

    loop = asyncio.get_running_loop()
    previous_sigint = signal.getsignal(signal.SIGINT)

    def handle_sigint(signum, frame):
        """Ctrl+C is always an interrupt while Conduit is running.

        Repeated presses are idempotent: they never escalate into a traceback or
        terminate the conversational shell. `/exit` remains the explicit way to
        close Conduit.
        """
        task = state.get("active_task")
        if task is not None and not task.done():
            if not state.get("interrupt_requested", False):
                state["interrupt_requested"] = True
                loop.call_soon_threadsafe(task.cancel)
            return

        # At the input prompt Conduit is already listening. Swallow SIGINT so an
        # accidental second press cannot cancel asyncio.run/main().
        print("\nConduit: Ready. I'm listening.", flush=True)

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        while True:
            try:
                user_text = await asyncio.to_thread(input, "\nYou: ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                # Defensive fallback for terminals/platforms that bypass the
                # custom SIGINT handler. Keep the session alive.
                print("\nConduit: Ready. I'm listening.")
                continue
            except asyncio.CancelledError:
                # A stray SIGINT must never unwind the top-level chat loop.
                print("\nConduit: Ready. I'm listening.")
                continue

            command = user_text.strip()
            if not command:
                continue
            normalized_command = normalize_conversation_command(command)
            lowered = normalized_command.casefold()

            provider_target = _detect_provider_switch(normalized_command)
            if provider_target == "gemini":
                await switch_to_gemini()
                continue
            if provider_target == "ollama":
                await switch_to_ollama()
                continue
            if provider_target == "openai":
                await switch_to_openai()
                continue

            if lowered in {
                "/exit",
                "exit",
                "quit",
                "exit conversation",
                "close conversation",
                "close conduit",
            }:
                break

            if lowered in {
                "/provider",
                "provider",
                "which provider",
                "what provider are you using",
            }:
                provider_status()
                continue

            if lowered in {
                "/switch gemini",
                "/online",
                "switch to gemini",
                "switch to online mode",
                "use gemini",
                "go online",
            }:
                await switch_to_gemini()
                continue

            if lowered in {
                "/switch ollama",
                "/local",
                "switch to ollama",
                "switch to local mode",
                "use ollama",
                "go local",
            }:
                await switch_to_ollama()
                continue

            if lowered in {
                "/switch openai",
                "switch to openai",
                "use openai",
                "switch to open ai",
                "use open ai",
            }:
                await switch_to_openai()
                continue

            if conversation._messaging_context.get("pending_message"):
                if lowered in {"yes", "y", "send", "send it", "confirm"}:
                    answer, report = await conversation.confirm_pending_message(True)
                    print("\nConduit:")
                    print(answer)
                    continue
                if lowered in {"no", "n", "cancel", "don't send", "do not send"}:
                    answer, report = await conversation.confirm_pending_message(False)
                    print("\nConduit:")
                    print(answer)
                    continue
                print("\nConduit: A message is waiting for send confirmation. Type YES to send it or NO to cancel it.")
                continue

            if lowered == "/clear":
                conversation.clear()
                print("Conduit: Conversation context cleared.")
                continue
            if lowered == "/history":
                if not conversation.history:
                    print("Conduit: No conversation turns yet.")
                else:
                    for index, turn in enumerate(conversation.history, 1):
                        print(f"\n{index}. You: {turn.user}")
                        print(f"   Conduit: {turn.assistant}")
                continue
            if lowered == "/actions":
                names = sorted(item.name for item in agent.actions.all())
                print(f"Conduit: {len(names)} registered actions")
                for name in names:
                    print(" -", name)
                continue

            state["last_action"] = None
            state["last_messaging_state"] = None

            # During an active task, the persistent SIGINT handler cancels only
            # this task. Multiple Ctrl+C presses remain harmless.
            active_task = asyncio.create_task(conversation.ask(command))
            state["active_task"] = active_task
            state["interrupt_requested"] = False

            try:
                answer, report = await active_task
            except asyncio.CancelledError:
                await conversation.interrupt()
                print("\nConduit: Interrupted. I'm listening.")
                continue
            except Exception as exc:
                print(f"\nConduit: I could not process that request: {exc}")
                continue
            finally:
                state["active_task"] = None
                state["interrupt_requested"] = False

            print("\nConduit:")
            print(answer)
            if not report.success:
                print(
                    f"\n[status: {report.status.value}; "
                    f"iterations: {report.iterations}]"
                )
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        await agent.close()
        if memory_manager is not None:
            memory_manager.close()

    print("Conduit session closed.")


if __name__ == "__main__":
    asyncio.run(main())
