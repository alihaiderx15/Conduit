# General PC Agent v1

General PC Agent v1 is the composition layer that gives Conduit's dynamic loop the complete enabled action catalog instead of a feature-specific subset.

It combines:

- Gemini or Ollama reasoning
- browser automation
- Windows system and file tools
- optional desktop keyboard/mouse control
- optional provider-backed screen vision
- task-scoped approvals
- persistent memory integration
- blind-retry prevention and observation-based recovery

Vision actions are hidden automatically when the selected model does not support images. `desktop.click` is also hidden because semantic desktop clicking depends on vision.

The agent prefers deterministic APIs and filesystem checks over GUI automation. It should verify goals with structured evidence before finishing.
