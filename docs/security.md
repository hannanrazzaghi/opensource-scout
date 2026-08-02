# Security design

This document explains the reasoning behind OpenSourceScout's safety model in
more depth than [SECURITY.md](../SECURITY.md); see that file for how to report
a vulnerability.

## Threat model

OpenSourceScout is designed to act with real GitHub write credentials against
repositories it does not own. The primary risks it defends against are:

1. **Unwanted public action on someone else's repository** — a spurious
   branch push, PR, comment, or issue edit made without the maintainer or the
   user actually wanting it.
2. **Credential leakage** — tokens ending up in logs, error messages, commit
   history, or LLM prompts.
3. **Unsafe command execution** — an LLM-driven agent running an
   under-specified or destructive shell command.
4. **Blind trust in LLM output** — treating an LLM's claims (a passing test,
   a correct root cause, a safe patch) as fact without evidence.

## Mitigations

### Approval gating (risk 1)

`workflows/state_machine.py` encodes `BRANCH_PUSHED` and `PR_OPENED` as gated
transitions: reaching either requires a valid, unexpired, single-use
`Approval` whose `kind` matches (`PUSH_EXTERNAL_BRANCH` /
`OPEN_EXTERNAL_PULL_REQUEST`). This check lives in the domain layer, not in
CLI argument parsing, so no code path can reach those states without going
through it. Approvals are:

- **Single-use** — `used_at` is set on consumption; a used approval fails
  `is_valid()` for any later check.
- **Expiring** — `is_valid(at=...)` also fails outside `[granted_at,
  expires_at]`.
- **Scoped** — tied to one `contribution_id` and one `ApprovalKind`; an
  approval for pushing a branch does not authorize opening a PR.

This authorization boundary is separate from — and does not extend to — the
pre-authorized commits/pushes OpenSourceScout makes to its own development
repository (`hannanrazzaghi/opensource-scout`).

### Credential handling (risk 2)

- `config.Settings` types `GITHUB_TOKEN` and `OPENAI_API_KEY` as
  `pydantic.SecretStr`; `repr()`/`str()` never expose the value, and
  `github_token_value()` / `openai_api_key_value()` are the only supported way
  to unwrap one, meant to be called immediately at the point of use (building
  a header) rather than stored.
- `logging.RedactionFilter` scans every log record — both the rendered
  message and `%`-style args — for token-shaped substrings (`ghp_...`,
  `github_pat_...`, `sk-...`, `Bearer ...`) and replaces them, as a
  defense-in-depth backstop independent of whether a call site logs a raw
  secret by mistake.
- `detect-secrets` runs via `pre-commit` and in the documented pre-commit
  checklist, against a tracked `.secrets.baseline` (hashes only, no secret
  material).
- `llm_calls` only ever stores prompt/response **hashes**, never raw content —
  it can't become a place where proprietary source or secrets leak into the
  database.

### Safe command execution (risk 3, Phase 5)

Every command an agent might run will be a typed specification — executable,
argument array, working directory, timeout, network requirement, expected
output, and risk classification — never a raw shell string
(`subprocess.run(["git", "status"], shell=False, ...)`-style, never
`shell=True`). Read-only git commands, `rg`, documented tests, and lint/format/
type checks run automatically; anything that touches an external remote,
credentials, or does a destructive git operation requires explicit approval.
`sudo`, unscoped deletion, SSH-key/browser-data reads, and privileged
containers are always blocked regardless of approval.

### Evidence over trust (risk 4)

Deterministic Python computes every score and validates every LLM-produced
value against declared ranges (`ScoreDimension`); malformed or evidence-free
assessments are rejected rather than silently accepted. Reproduction reports
require an explicit status (`CONFIRMED`, `NOT_REPRODUCED`,
`ENVIRONMENT_BLOCKED`, ...) backed by evidence — "confirmed" is never asserted
without it. Claude Pro's manually-imported feedback is parsed into structured
data, treated as untrusted input, and checked against repository evidence
before being surfaced — never executed as instructions.
