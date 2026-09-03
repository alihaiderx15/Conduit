# Conduit architecture — foundation milestone

This clean repository deliberately contains no UI, PyAutoGUI, planner, memory,
or large action collection yet. The first milestone is a stable provider layer.

## Dependency direction

`core models -> provider interface -> provider adapters -> provider manager`

Everything added later must depend on the `AIProvider` interface, never directly
on Gemini or Ollama.

## Provider contract

Each provider exposes:

- model discovery
- chat
- provider-neutral tool calls
- image understanding
- capability metadata
- resource cleanup

## Tool schemas

The registry will store one portable JSON schema. Each provider adapter converts
it into its own wire format. Unsupported schema keywords are stripped centrally,
which prevents the Gemini `additional_properties` failure found in the prototype.

## Next milestone

Create the typed Tool Registry and Executor with no real desktop side effects.
Tests will use safe fake tools before Windows actions are introduced.

## Module 6: Structured Vision Engine

The observer can request strict JSON perception from any vision-capable provider. Model output is parsed into bounded `ScreenElement` objects, searched through `ScreenLocator`, and compared across captures by the verifier. Coordinates remain inside the perception/controller boundary. `ObserveActWorkflow` requires explicit approval before clicking and captures a second screen state for verification.

## Module 7A: Event Bus

Conduit modules can publish immutable events through `EventBus` without knowing
which UI, logger, voice layer, telemetry sink, or plugin consumes them.
Subscriptions support exact names and wildcard patterns such as `tool.*` and
`*`. Synchronous and asynchronous handlers are supported, and one subscriber's
failure cannot stop delivery to the others.

Current event-producing integrations include:

- Assistant turn lifecycle
- Tool start, completion, failure, and confirmation requests
- Screenshot capture
- Desktop input action start and completion
