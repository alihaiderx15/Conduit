# Conduit — Local Windows AI Copilot

Conduit is a local-first, provider-neutral desktop AI assistant for Windows. It combines a chat GUI, a dynamic reasoning loop, and a set of specialist agents that can write and run code, manage files, browse the web, control the desktop, and manage games — backed by short-term session memory and long-term persistent memory.

Conduit is not a single chatbot script. It's a modular runtime: a main dynamic agent loop decides which specialist should handle a request, and each specialist (coding, dev projects, files, games, browser, memory, environment setup, proactive engine) is a separate, testable module.

## Features

**AI Providers**
- Ollama (local), Google Gemini, OpenAI, and Grok/xAI, switchable from the GUI
- Masked API-key entry for cloud providers
- Quota/error recovery — offers switching keys, providers, or Ollama instead of dumping raw API errors
- Ollama model manager: shows installed models with a specialty tag (coding, vision, chat, reasoning, general), recommends `qwen2.5vl:7b` and `qwen2.5-coder:7b`, and installs models or Ollama itself asynchronously without blocking the GUI

**Memory**
- Session memory for the running conversation (files created/edited, tasks, references like "that" or "the previous file")
- Long-term persistent memory (SQLite-backed) for stable facts, explicit preferences, and repeated behavior, surviving restarts
- Session summaries/recap carried into the next session and marked consumed after use
- Natural-language equivalents for memory commands (e.g. "clear our conversation" instead of `/clear`)

**Coding**
- Single-file code helper: generate, edit, explain, review, run, test, debug, optimize, install dependencies
- Multi-file developer agent: plan, scaffold, install dependencies, run, test, analyze errors, patch, and open in an editor
- Progress-based monitoring instead of rigid timeouts for long-running coding/build tasks

**Automation**
- Playwright-based browser engine: navigate, read page state, extract text, scroll, and a YouTube capability
- Desktop control via PyAutoGUI (mouse/keyboard) and Windows-native system control
- File processing for documents, spreadsheets, PDFs, presentations, images, and archives
- Games manager for Steam/Epic: list, install, update, check download status, schedule updates, launch

**Other**
- Event bus, task planner, unified action/capability registry with permission levels
- Proactive engine (policy, cooldowns, context-aware trigger) for optional check-ins
- Text-to-speech with a 50-word spoken-summary cap (full answers always appear in the chat)
- `setup.py` environment bootstrapper that creates/repairs a virtual environment, bootstraps `pip`, installs dependencies, Playwright Chromium, and verifies Ollama

## Status

This is an active, module-by-module build. Most of the architecture above is implemented and covered by the automated test suite (165+ tests across providers, memory, planning, dynamic agent, browser engine, desktop control, games, and file processing). A few pieces — GUI DPI/scaling polish, some games-manager verification paths, and parts of the proactive engine — are still being finished. Check `docs/` and the module under `conduit/` you care about before relying on it in production use.

For the module-by-module build history (what each version/module added and how to smoke-test it), see `CHANGELOG.md`.

## Project Structure

```
Conduit/
├── main.py             # Launches Conduit through the venv created by setup.py
├── setup.py            # Environment bootstrapper (venv, pip, dependencies, Playwright, Ollama)
├── requirements.txt / pyproject.toml
├── conduit/             # Application package
│   ├── gui/                # Desktop GUI (PySide6)
│   ├── dynamic_agent/      # Main reasoning loop (decide → act → observe → reconsider)
│   ├── providers/          # Ollama / Gemini / OpenAI / Grok adapters + manager
│   ├── memory/             # Session memory, long-term memory, recap, retrieval
│   ├── code_helper/        # Single-file coding specialist
│   ├── dev_agent/          # Multi-file project developer specialist
│   ├── browser/            # Playwright browser engine
│   ├── desktop/            # Mouse/keyboard/desktop control
│   ├── games/              # Steam/Epic games manager
│   ├── file_processing/    # Documents, spreadsheets, PDFs, images, archives
│   ├── environment/        # Runtime/dependency verification
│   ├── proactive/          # Proactive check-in engine
│   └── planning/, actions/, tools/, execution/, events/, ...
├── docs/                 # Architecture and design notes
├── scripts/              # Manual smoke tests for individual modules
└── tests/                # Automated test suite (pytest)
```

## Setup and Running (Windows)

Open the Folder in VS code or CMD.Conduit needs Python 3.11–3.13. Run setup once, then launch with `main.py`:

```cmd
py setup.py
py main.py
```

`setup.py` creates and repairs a local `.venv`, bootstraps `pip` if missing, installs all required Python packages, installs Playwright's Chromium browser, and verifies the Ollama installation and recommended models. `main.py` re-launches itself inside that `.venv` automatically, so you can also just run `py main.py` after setup — it will tell you to run setup first if the environment isn't ready.

You can also use the bundled bootstrap scripts:

```cmd
SETUP_CONDUIT.bat
```
or
```powershell
SETUP_CONDUIT.ps1
```

For development:

```cmd
.venv\Scripts\python.exe -m pytest
```

## API Keys

Conduit never requires API keys to be committed to the repo. Supply cloud-provider credentials at runtime via environment variables or the GUI's masked key dialog:

- `GEMINI_API_KEY`
- `OPENAI_API_KEY`
- `XAI_API_KEY`

`.gitignore` already excludes local credential, config, database, log, cache, build, and virtual-environment files. See `SECURITY.md` for vulnerability disclosure guidance. If a key is ever exposed, revoke/rotate it immediately with the provider.

## Testing

Every module has a corresponding automated test and, for the larger integrations, a manual smoke-test script under `scripts/` (provider connectivity, browser engine, dynamic agent, memory, games, desktop control, etc.). Run the full suite with:

```cmd
.venv\Scripts\python.exe -m pytest
```

## License

MIT — see `LICENSE`.
