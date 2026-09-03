# Security Policy

## Reporting a vulnerability

Please report suspected security vulnerabilities privately to the project maintainer rather than opening a public issue containing exploit details or credentials. Include the affected version, reproduction steps, and expected impact when possible.

## API keys and credentials

Do not commit real API keys, access tokens, passwords, private keys, or `.env` files to this repository. Conduit reads provider credentials at runtime, including `GEMINI_API_KEY`, `OPENAI_API_KEY`, and `XAI_API_KEY`.

If a credential is exposed in a commit, log, screenshot, issue, release archive, or other public location:

1. Revoke or rotate the credential immediately at the provider.
2. Remove the secret from the current files.
3. If necessary, purge it from Git history before republishing.
4. Review provider usage/audit logs for unexpected activity.

The `.gitignore` is defense in depth only; it is not a substitute for checking changes before committing.

## Supported versions

Security fixes should be applied to the latest published release.
