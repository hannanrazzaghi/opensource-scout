# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities privately rather than opening a public
issue. Use GitHub's private vulnerability reporting for this repository:

<https://github.com/hannanrazzaghi/opensource-scout/security/advisories/new>

Include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce, or a proof of concept if available.
- Any known mitigations.

We aim to acknowledge reports within a few days. Please do not disclose the
issue publicly until it has been addressed.

## Scope

This policy covers the OpenSourceScout codebase itself: the CLI, its GitHub and
OpenAI integrations, the command-execution safety layer, and the approval
system. It does not cover the external repositories OpenSourceScout discovers
or interacts with — report vulnerabilities in those projects through their own
security policies.

## Safety model summary

- No unrestricted shell access is ever given to an LLM. Commands are typed,
  argument-array specifications with declared risk classifications; `sudo`,
  unscoped deletion, credential/SSH-key access, and privileged containers are
  always blocked.
- Every action affecting an external repository (pushing a branch, opening a
  PR, commenting, closing an issue) requires an explicit, single-use, expiring
  human approval before it can execute.
- Secrets (`GITHUB_TOKEN`, `OPENAI_API_KEY`) are stored as `pydantic.SecretStr`
  and are never written to logs; a redaction filter also scrubs token-shaped
  strings defensively.
- `detect-secrets` runs in CI-equivalent local checks and in `pre-commit` to
  catch accidental credential commits before they happen.

See [docs/security.md](docs/security.md) for the full design rationale.
