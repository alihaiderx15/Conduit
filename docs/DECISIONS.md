# Technical decisions

## 001 — Clean restart

The v0.x prototypes proved Gemini and Ollama connectivity but mixed UI, tools,
provider schemas, and execution logic. This repository starts clean.

## 002 — Native APIs

Gemini uses Google's `google-genai` SDK. Ollama uses its native `/api/chat` and
`/api/tags` endpoints. Compatibility APIs are avoided in the core adapter.

## 003 — No hardcoded model

Providers list models; application configuration selects one. The provider
layer rejects empty model values.

## 004 — Vision remains provider-neutral

Both adapters expose `describe_image`. Ollama transport supports images, while
actual success depends on the chosen local model.
