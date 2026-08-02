# Architecture

## Layers

```text
src/opensource_scout/
├── cli.py            # Typer entry point; thin — delegates to workflows/reports
├── config.py          # pydantic-settings; SecretStr credentials, budgets
├── logging.py          # structured JSON logging + secret redaction filter
├── domain/            # Pydantic models: Profile, RepositoryCandidate,
│                       # IssueCandidate, scores, ContributionRecord, Approval,
│                       # WorkflowState — the storage-agnostic source of truth
├── db/                 # SQLAlchemy 2 ORM rows + Alembic migrations;
│                       # a separate, storage-shaped mirror of domain/
├── workflows/          # state_machine.py: the transition table and approval
│                       # gating for BRANCH_PUSHED / PR_OPENED
├── github/             # REST + GraphQL clients, discovery (Phase 2)
├── scoring/            # deterministic project/issue scoring (Phase 2)
├── repository/         # contribution-rule extraction (Phase 3)
├── llm/                # OpenAI Responses API client, model router,
│                       # cost/token budgets, context builder (Phase 4)
├── execution/           # safe command runner, workspace manager (Phase 5)
│                       # workflows/reproduction.py, workflows/implementation.py
├── approvals/           # approval issuance/validation (Phase 6)
├── claude_bridge/        # export/import for the Claude Pro review loop (Phase 6)
└── reports/             # Rich/Jinja2 rendering of scores and reports
```

Domain models (`domain/`) and ORM rows (`db/models.py`) are kept deliberately
separate. The domain layer is what business logic (scoring, the state machine)
is written and tested against; conversion to/from SQLAlchemy rows happens
explicitly at the persistence boundary. This keeps the domain layer free of
ORM session/lazy-loading concerns and easy to unit test with plain Python
objects.

## Workflow state machine

`workflows/state_machine.py` holds a single source of truth: a
`dict[WorkflowState, frozenset[WorkflowState]]` transition table. Every state
change is validated against it and produces a `TransitionRecord`, which
callers persist as a row in `workflow_transitions`. Because the current state
of any contribution is just "replay its transition log in order," the
workflow survives a process restart with no separate recovery machinery.

Two states are specially gated: `BRANCH_PUSHED` and `PR_OPENED` represent
OpenSourceScout acting on an *external* repository. Reaching either requires
passing a valid, unexpired, single-use `Approval` of the matching
`ApprovalKind` — enforced in `validate_transition`, independent of whatever
CLI command or workflow code calls it. This is what makes "never push or open
a PR on someone else's repo without a human approving that exact action" a
property of the state machine itself, not a convention call sites have to
remember to follow.

OpenSourceScout's own development repository does not use this workflow at
all — commits and pushes to `hannanrazzaghi/opensource-scout` are made
directly by the assistant under the separate authorization described in the
project's operating instructions, not through the approval-gated contribution
workflow.

## Persistence

SQLite via SQLAlchemy 2, migrated with Alembic (`alembic/`). Tables:
`projects`, `issues`, `contributions`, `workflow_transitions`, `approvals`,
`llm_calls`, `command_runs`, `http_cache`. `db.session.ensure_database`
creates the schema directly from ORM metadata for fresh local databases and
tests; `alembic upgrade head` is the production upgrade path.

## GitHub integration (Phase 2)

An async HTTPX client behind a `GitHubClient`-shaped interface so tests
substitute fakes instead of hitting the network. Handles pagination via
`Link` headers, tracks `X-RateLimit-*` and sleeps pre-emptively rather than
retrying into a 403, uses ETags for conditional requests cached in
`http_cache`, retries 5xx/secondary-rate-limit errors with Tenacity backoff,
and bounds concurrency with `asyncio.Semaphore(GITHUB_CONCURRENCY)` (default
4). A GraphQL client batches repository metadata + community-health files +
recent activity into one request where that's cheaper than several REST
calls.

## Scoring (Phase 2)

Deterministic, not LLM-driven. `scoring/project.py` computes six bounded
dimensions (`career_relevance` 0–30, `acceptance_probability` 0–20,
`technical_depth` 0–15, `maintainer_activity` 0–15, `hardware_compatibility`
0–10, `repeat_contribution_value` 0–10) as plain Python, validates every input
range, applies explicit penalties (archived, unlicensed, stale, GPU-only,
tutorial/promotional repos), and sums to a 0–100 total. `domain.models.
ScoreDimension` enforces the range invariant at construction time, so a
malformed or evidence-free score can't silently enter a ranking. LLM-produced
subjective assessments (`domain.llm_models.ProjectAssessment` /
`IssueAssessment`, Phase 4) are optional inputs into this same validated
shape, not a replacement for it — a bad LLM output is rejected by the model,
not trusted. No CLI command wires an assessment call into scoring yet; the
models and range validation exist and are tested, but `oss discover
projects`/`issues` remain fully deterministic today.

## LLM routing (Phase 4)

Three logical roles — fast / reasoning / coding — map to configured model
names (`OPENAI_MODEL_FAST/_REASONING/_CODING`); the same model may serve
multiple roles, and a role never silently escalates to a more expensive model
when its configured one is unavailable (`llm.router.ModelUnavailableError`).
`llm.client.OpenAiClient` wraps `AsyncOpenAI.responses.parse`, requiring a
Pydantic `response_model` for every call — there is no unstructured "just ask
the model" path. Malformed output (including the raw `pydantic.ValidationError`
the SDK raises when the model's text doesn't match the schema) is retried
once, then raised. Every call is recorded in `llm_calls` (cost/token metadata
only, never raw prompt/response content) and checked against daily/monthly
budgets and a per-workflow call-count limit *before* it's made. Identical
`(model, task_category, prompt)` requests are served from `llm_cache` instead
of being re-billed.

## Deterministic context construction (Phase 4)

`llm.context.build_context_bundle` ranks candidate files by lexical overlap
with a set of query terms and selects a bounded, token-budgeted subset — an
LLM is never handed an unfiltered repository dump. Files with zero overlap
are excluded even when token budget remains.

## Safe execution and reproduction (Phase 5)

`execution.command.run_command` executes every command as a declared
`CommandSpec` — executable, argument array, working directory, timeout, risk
classification — and never via a shell string. A fixed blocklist
(`sudo`/`doas`/`su`, SSH-key/AWS-credential paths, `--privileged`, `git push
--force`, `git reset --hard`, unscoped recursive deletion) is enforced
regardless of the command's declared risk level; a scoped `rm -rf` inside the
command's own working directory is the one case recursive deletion is
allowed. `execution.workspace` clones a repository into an isolated,
per-contribution directory (refusing to delete anything outside the
workspace root even under a crafted contribution ID).

`workflows.reproduction.reproduce_issue` runs a test command against a fresh
clone and classifies the result as `CONFIRMED` (non-zero exit — evidence of
the failure), `NOT_REPRODUCED` (zero exit — doesn't mean the issue is
invalid, only that this command didn't show it), `NEEDS_CLARIFICATION` (no
test command available), or `ENVIRONMENT_BLOCKED` (clone/checkout failed or
the command timed out). `workflows.implementation.plan_implementation` calls
the reasoning-role LLM over a context bundle to produce a structured
`ImplementationPlan`; `validate_contribution` runs the repository's own
test/lint/format/typecheck commands and reports `PASSED`/`FAILED`/
`TIMED_OUT`/`UNAVAILABLE` per command. Neither function writes code to disk —
a plan is for human review, not automatic application.

## Claude Pro bridge (not yet built — Phase 6)

`oss claude export` renders a Markdown review packet from repository rules,
issue/plan/diff context, and test evidence. Claude's pasted-back response is
parsed by `oss claude import` into structured feedback, treated as untrusted
input, checked against repository evidence, and surfaced to the user — never
executed automatically.
