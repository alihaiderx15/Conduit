# Changelog

This file records Conduit's build history module by module — what was added, why, and how to manually verify it with the smoke-test scripts in `scripts/`. For the current feature overview and setup instructions, see `README.md`. For architecture rationale, see `docs/DECISIONS.md`.

---

## Provider Layer (v0.x)

Provider-neutral foundation. Included:

- Gemini adapter using `google-genai`
- Ollama adapter using the native local API
- Model discovery
- Text chat
- Function/tool call parsing
- Gemini and Ollama image understanding
- Portable tool-schema normalization
- Provider manager
- Unit tests and a manual smoke-test script

Gemini smoke test:
```cmd
set GEMINI_API_KEY=your_key_here
py scripts\provider_smoke_test.py gemini --model YOUR_WORKING_MODEL
```

Ollama smoke test:
```cmd
py scripts\provider_smoke_test.py ollama --model qwen3:8b
```
Expected result for the prompt `Open calculator` is a parsed tool call named `open_calculator`; the script intentionally does not execute it.

## Tool Engine

```cmd
py -m pip install -e .
py -m pytest
py scripts\tool_engine_smoke_test.py calculator
py scripts\tool_engine_smoke_test.py confirmation
```
The confirmation smoke test does not create anything; it should print a `PendingConfirmation` value.

## v0.3 — Assistant Orchestrator

Connects the selected provider to the tool registry and executor. Supports normal tool execution, confirmation pauses, cancellation, feeding structured tool results back to the model, and multi-round tool use.

Full terminal loop:
```cmd
py scripts\orchestrator_smoke_test.py ollama --model qwen3:8b
```
With Gemini:
```cmd
set GEMINI_API_KEY=YOUR_KEY
py scripts\orchestrator_smoke_test.py gemini --model gemini-flash-latest
```

## Module 4 — Desktop Observer

Captures the Windows desktop, reads foreground-window metadata, and sends a screenshot to the selected provider for visual analysis. Screenshot analysis is read-only: this module does not move the mouse, click, or type. Gemini can be tested immediately. Ollama first checks `/api/show` and refuses a text-only model with a clear message instead of sending an invalid image request.

## Module 5 — Desktop Controller

Validated mouse and keyboard control through PyAutoGUI. All modifying desktop tools are marked `CONFIRM`; read-only screen size and pointer position tools remain `SAFE`. Move the pointer to the top-left corner to trigger PyAutoGUI's emergency fail-safe.

```cmd
py scripts\desktop_controller_smoke_test.py info
py scripts\desktop_controller_smoke_test.py move --x 500 --y 400
py scripts\desktop_controller_smoke_test.py type --text "Conduit desktop control is working."
```

## Module 7A — Event Bus

Typed, async-aware internal event bus with wildcard subscriptions, unsubscribe handles, subscriber error isolation, and hooks for assistant turns, tools, permission confirmations, screenshots, and desktop actions.

```cmd
py scripts\event_bus_smoke_test.py
```

## Module 7B — Browser Engine

Managed Playwright Chromium session with semantic targets, structured page state, visible-text extraction, scrolling, downloads, and browser lifecycle events. After installation run `py -m playwright install chromium` once.

## Module 8 — Structured Task Planner

Turns a natural-language goal into a validated, provider-neutral plan. The planner only uses actions from its capability catalog, validates dependencies, retries malformed model output once, and emits planning lifecycle events. Does not execute the generated plan itself.

```cmd
py scripts\planner_smoke_test.py ollama --model qwen3:8b
py scripts\planner_smoke_test.py gemini --model gemini-flash-latest
```

## v1.0 — Integrated Plan Executor and YouTube Capability

Executes validated plans across the tool and browser engines. The executor honors step dependencies, emits progress events, retries failed steps, blocks dependent work after failures, and pauses protected steps for approval.

A reusable YouTube capability opens a channel's Videos page, selects the first standard `/watch` upload, opens it, and verifies the playback URL. This keeps website-specific DOM knowledge outside the generic browser engine.

Direct YouTube capability test:
```cmd
py scripts\youtube_agent_smoke_test.py --channel aceu
```

Full planner + executor test with Ollama:
```cmd
py scripts\integrated_agent_smoke_test.py ollama --model qwen3:8b
```

Full planner + executor test with Gemini:
```cmd
set GEMINI_API_KEY=YOUR_KEY
py scripts\integrated_agent_smoke_test.py gemini --model gemini-flash-latest
```

## Phase 2 — Dynamic Agent Loop

Reasons one action at a time instead of generating and blindly executing a complete plan:

```text
Goal -> Decide one action -> Execute -> Observe -> Reconsider -> Finish or recover
```

The working context records structured observations and variables after every action. Completion is accepted only when the model points to evidence in the current browser state or previous action results. Repeated failures and maximum-iteration limits stop runaway loops.

Controlled local-page smoke test:
```cmd
py scripts\dynamic_agent_smoke_test.py ollama --model qwen3:8b
```
Or with Gemini:
```cmd
set GEMINI_API_KEY=YOUR_KEY
py scripts\dynamic_agent_smoke_test.py gemini --model gemini-flash-latest
```
The test asks the agent to open a local HTML page, fill a labeled input, click Submit, observe the changed page, and finish only after the expected submitted text is visible.

## Phase 2.2 — Execution Context and Reusable Variables

Dynamic actions can retain useful outputs and reuse them in later steps. An `act` decision may include a `save_as` mapping from a variable name to an action result path:

```json
{
  "decision": "act",
  "action": "browser.read_page",
  "arguments": {},
  "save_as": {
    "page_title": "data.title",
    "page_url": "data.url"
  }
}
```

Later arguments can reference those values with double braces:

```json
{
  "text": "{{page_title}}",
  "url": "{{page_url}}"
}
```

The context also retains `last`, `last_success`, `last_failure`, and numbered `step_N` records, including action arguments, messages, data, and error details. Unknown references become failed observations so the agent can recover instead of crashing.

Deterministic browser-based context test:
```cmd
py scripts\context_variables_smoke_test.py
```

## Module 9 — Local Memory

Privacy-first persistent memory backed by a local SQLite file. Supports conversations, long-term facts and preferences, project facts, full-text search, expiry, update/delete operations, and basic credential filtering. JSON remains suitable for simple application settings; durable memory belongs in SQLite.

```cmd
py scripts\memory_smoke_test.py
```

## Module 9.1 — Memory-Aware Dynamic Agent

The dynamic agent can optionally use an `AgentMemoryBridge` to retrieve relevant local SQLite memories before each run. Retrieved memories are included as user context, not executable instructions. The model may also propose durable memories. The default `PROPOSE_ONLY` policy requires future user approval; `AUTO_SAFE` is available for controlled tests and still applies credential/privacy filtering.

```cmd
py scripts\memory_agent_integration_smoke_test.py
```

## v1.5 — Unified Action Layer

Exposes browser, desktop, vision, Windows system, and file actions through one typed capability registry. Agents can reason over the same action catalog while risk levels remain enforced by the existing permission system.

```cmd
py scripts\unified_action_smoke_test.py
```

## v1.6 — Task-Scoped PC Copilot

Adds narrowly scoped one-time approvals for multi-step desktop tasks.

```cmd
py scripts\pc_copilot_smoke_test.py
```
Tests Notepad typing, saving, and filesystem verification (Windows only).

## General PC Agent v1

End-to-end natural-language benchmark:
```cmd
py scripts\general_pc_agent_smoke_test.py ollama --model qwen3:8b
```
or with Gemini:
```cmd
set GEMINI_API_KEY=YOUR_KEY
py scripts\general_pc_agent_smoke_test.py gemini --model gemini-flash-latest
```
The benchmark grants a narrow one-task approval, then lets the model independently choose file and system actions and verify the result.

## v3.1.8 — Memory Fix / Current

- Fixed provider-switching phrases ("switch to Gemini") being misrouted to `browser.goto` instead of the provider manager.
- README restructured: feature overview and setup moved to `README.md`; module-by-module build history moved to this file.

---

## Format going forward

New entries should follow this pattern:

```
## <version or module name> — <short title>

What changed and why, in a few sentences.

Manual verification:
\`\`\`cmd
py scripts\<smoke_test>.py
\`\`\`
```
