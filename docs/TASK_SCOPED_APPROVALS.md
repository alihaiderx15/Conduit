# Task-scoped approvals

Conduit can approve a narrow set of confirmation-requiring actions for one agent run. A scope contains the exact goal, allowed action names, optional approved path roots, argument constraints, an action-use limit, and an expiry time.

The scope never expands itself. An action outside the approved set, a file path outside an approved root, or a constrained argument with a different value is blocked and falls back to normal per-step confirmation.

This enables multi-step desktop workflows without asking before every harmless keystroke while preserving a clear safety boundary.
