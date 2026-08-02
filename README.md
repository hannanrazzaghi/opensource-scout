# OpenSourceScout

A local-first AI engineering assistant for discovering, evaluating, and completing
high-quality open-source contributions.

> OpenSourceScout is an engineering assistant, not an autonomous contribution bot.
> Users are responsible for understanding and reviewing every public contribution.

> **Status:** Foundation, GitHub discovery, issue intelligence, the LLM
> reasoning layer, and safe reproduction/implementation workflows are
> implemented. The Claude review bridge and PR workflow are not yet built. See
> [docs/progress.md](docs/progress.md) for exact status and
> [docs/architecture.md](docs/architecture.md) for how the pieces fit together.

## What it does

OpenSourceScout helps a developer:

1. Discover valuable open-source projects.
2. Rank projects by career relevance and contribution feasibility.
3. Find suitable issues and detect competing work.
4. Read a repository's contribution rules.
5. Reproduce issues locally.
6. Plan and implement focused fixes.
7. Run tests and quality checks.
8. Prepare accurate pull requests.
9. Track merged contributions and generate verified résumé material.

It is built for one specific developer profile (see `oss profile show`) and is
tuned for a CPU-only MacBook Air: no CUDA, no large-model training, no expensive
cloud dependencies.

## Installation

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/hannanrazzaghi/opensource-scout.git
cd opensource-scout
uv sync --all-groups
cp .env.example .env   # then fill in GITHUB_TOKEN / OPENAI_API_KEY
uv run oss init
uv run oss doctor
```

## Configuration

All configuration is environment-variable driven; see [.env.example](.env.example)
for the full list. Nothing in `.env` is ever committed — it's git-ignored, and every
credential is stored as a `pydantic.SecretStr` internally so it can't leak into logs,
reprs, or error messages.

Key variables:

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` | Read access for discovery; write access only for approved actions |
| `OPENAI_API_KEY` | Programmatic LLM calls (classification, planning, PR drafting) |
| `OPENAI_MODEL_FAST` / `_REASONING` / `_CODING` | Logical model roles — never hard-coded |
| `DAILY_OPENAI_BUDGET_USD`, `MONTHLY_OPENAI_BUDGET_USD` | Hard spend caps |
| `GITHUB_CONCURRENCY` | Default `4` — bounded concurrent GitHub requests |

### GitHub permissions

Read-only access is used for all discovery. Write access is used only for:

- The `opensource-scout` repository itself (this project's own development).
- Explicitly human-approved actions on external repositories (see **Safety model**
  below).

### OpenAI configuration

OpenSourceScout uses the official OpenAI Python SDK and the Responses API for all
programmatic LLM work — repository classification, issue triage, root-cause
reasoning, implementation planning, patch assistance, and PR drafting. Three
logical model roles (fast / reasoning / coding) are configured independently so
cheap tasks never run on an expensive model, and the model actually used is never
silently swapped for a costlier one.

### Claude Pro workflow

Claude is never called programmatically — there is no Anthropic API key in this
project. Instead, `oss claude export <type> <id>` generates a Markdown review
packet (repository rules, issue summary, relevant source context, proposed plan
or diff, test evidence) that you paste into Claude Pro manually. `oss claude
import <file>` parses Claude's structured response back into advisory feedback:
it is stored, validated against repository evidence, and presented to you — never
executed automatically.

## Cost controls

Before every LLM call: the cache is checked, input size is estimated, the
workflow's call budget is checked, irrelevant context is stripped, and the
cheapest suitable model is chosen. After every call: model, token usage,
estimated cost, and prompt/response hashes are recorded. `oss cost today` / `oss
cost month` report spend against the configured budgets. A repository is never
sent to an LLM in full — deterministic search (ripgrep, Tree-sitter, BM25, git
history) narrows context first.

## Safety model

- **Deterministic scoring.** Project and issue scores are computed by plain
  Python, not an LLM. Every dimension is range-validated; malformed or
  evidence-free LLM assessments are rejected outright.
- **No unrestricted shell access.** Every command an agent might run is a typed,
  argument-array specification (never `shell=True`) with a declared working
  directory, timeout, network requirement, and risk classification. Destructive
  operations, credential access, and privileged execution are always blocked.
- **Approval gates.** For any repository other than this one, OpenSourceScout
  can never push a branch, open a pull request, comment, or otherwise act
  publicly without an explicit, single-use, expiring human approval recorded in
  the local database. The `AWAITING_PUSH_APPROVAL` / `AWAITING_PR_APPROVAL`
  workflow states exist specifically to enforce this.
- **This repository is different.** Commits and pushes to
  `hannanrazzaghi/opensource-scout` — OpenSourceScout's own development — are
  pre-authorized and don't require per-action approval; every other repository
  discovered by the tool does.

## Development

```bash
uv sync --all-groups
uv run pytest --cov=opensource_scout --cov-report=term-missing
uv run ruff check . && uv run ruff format --check .
uv run pyright
uv run pre-commit install
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow and
[docs/development.md](docs/development.md) for local setup details.

## Current limitations

- GitHub repository discovery, deterministic project scoring, issue
  discovery/scoring, competing-work detection, and repository contribution-
  rule extraction are implemented (`oss discover projects`, `oss discover
  issues`).
- The OpenAI Responses client, model router, structured outputs, cost/budget
  tracking, and deterministic context builder are implemented and now used
  by `oss contribution plan`. Issue/project *assessment* (as opposed to
  implementation planning) still doesn't call the LLM layer yet.
- Safe, sandboxed command execution, isolated per-contribution workspaces,
  issue reproduction, implementation planning, and validation are
  implemented (`oss issue reproduce`, `oss contribution
  plan/implement/validate/status`). OpenSourceScout does not write code to
  disk automatically — a generated plan is for human review, not
  auto-application.
- No PR preparation, GitHub mutation commands, approval system, contribution
  ledger, or résumé generation yet (Phase 6).
- The Claude Pro export/import bridge does not exist yet.

## Roadmap

| Milestone | Scope |
|---|---|
| v0.1.0 | Foundation and project discovery skeleton |
| v0.2.0 | GitHub discovery and deterministic project scoring |
| v0.3.0 | Issue intelligence and repository rule extraction |
| v0.4.0 | LLM reasoning and context construction |
| v0.5.0 | Safe reproduction and implementation workflows |
| v1.0.0 | Claude review bridge, PR workflow, contribution ledger |

## License

[MIT](LICENSE)
