# 1. Use a plain Python state machine instead of an agent framework

## Status

Accepted

## Context

OpenSourceScout coordinates a long-running, multi-step workflow (discovery →
issue selection → reproduction → implementation → validation → PR → merge)
that mixes deterministic logic, LLM calls, and human approval gates. Frameworks
like LangChain or general multi-agent orchestration libraries are a common
default for this kind of coordination.

## Decision

Version one implements the workflow as an explicit
`dict[WorkflowState, frozenset[WorkflowState]]` transition table in plain
Python (`workflows/state_machine.py`), not through LangChain or a
multi-agent framework.

## Rationale

- **Auditability.** Every legal transition is visible in one table. Approval
  gating on `BRANCH_PUSHED`/`PR_OPENED` is a property enforceable at that one
  choke point, not something that has to be re-verified across an
  orchestration graph.
- **Safety.** This project's core requirement is that OpenSourceScout never
  acts publicly on someone else's repository without a specific human
  approval. That's much easier to guarantee — and to unit test exhaustively —
  as a small, explicit state machine than as emergent behavior of an agent
  framework's planning loop.
- **Debuggability.** A `TransitionRecord` and a replayable
  `workflow_transitions` table are enough to reconstruct exactly what happened
  and why, without needing framework-specific tracing.
- **Dependency weight.** Agent frameworks pull in significant surface area
  (their own tool-calling conventions, memory abstractions, prompt templates)
  for a workflow that, at its core, doesn't need dynamic planning — the states
  and their legal transitions are known in advance.

## Consequences

- LLM calls (Phase 4) are invoked directly through the OpenAI SDK at specific,
  known points in the state machine — not through an agent that decides for
  itself which tool to call next.
- Adding a genuinely new workflow state requires an explicit, reviewed change
  to the transition table, not just a prompt change.
- If a future version needs dynamic multi-step planning that this table
  can't express, that's a deliberate, revisitable decision — not something
  adopted by default.
