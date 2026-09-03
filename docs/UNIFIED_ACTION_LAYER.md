# Unified Action Layer

The unified action layer is the bridge between Conduit's reasoning systems and its execution backends.

- `UnifiedActionRegistry` describes every action visible to planners and dynamic agents.
- `UnifiedActionRouter` routes browser, desktop, vision, and normal tool actions.
- Normal tools continue to use `ToolExecutor`, argument validation, risk levels, and confirmations.
- Browser actions use Playwright.
- Desktop actions use the validated `DesktopController`.
- Vision actions use the provider-neutral `DesktopObserver` when the selected model supports images.

Current action groups include browser navigation and interaction, screen observation, desktop mouse/keyboard input, Windows application launching, process listing, and local file operations.
