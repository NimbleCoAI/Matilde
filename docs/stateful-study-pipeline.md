# Stateful Study Pipeline (design)

## Motivation

Long analyses — e.g. validating a paper's findings against an OpenNeuro dataset —
currently run **inline in a single agent turn**: one-shot scripts that

- **die on OOM** (observed 2026-06-22: a live MEG M100 validation full-preloaded a
  2.5 GB dataset into the agent container and was OOM-killed), and
- **lose all state when the container restarts** (the same session's analysis was
  wiped when the agent image was rebuilt mid-run — no resume, no memory of it).

Both failure modes have the same remedy: **durable, checkpointed analysis state**
so an analysis resumes from the last completed step after an OOM *or* a container
rebuild, instead of vanishing.

## Hard requirements

1. **Survives container rebuild** — study state lives on the mounted data volume
   (`HERMES_HOME`/Matilde engagements dir), not in process memory.
2. **Survives OOM / mid-step failure** — a failed step leaves the study resumable;
   completed steps are never re-run.
3. **Stdlib-only core** — mirrors the rest of `matilde_plugin/engine` (pure,
   injected-I/O, SQLite from stdlib). Heavy scientific deps (mne, etc.) live only
   in optional step implementations, never in the framework.
4. **Agent-drivable** — the agent kicks off / advances / inspects a study through
   tools, so it never has to hold a long analysis in a single turn.
5. **TDD** — injected I/O, deterministic, matches the existing ~99-test suite.

## Components

### `matilde_plugin/engine/store.py` — `StudyStore` (SQLite)

Persistent store; injected db path (default under the engagements dir). WAL,
atomic writes. Tables:

- `studies(id, slug UNIQUE, title, status, plan_json, created_at, updated_at, meta_json)`
  - status: `created | running | done | failed | blocked`
- `steps(id, study_id, idx, name, status, result_json, error, started_at, finished_at)`
  - status: `pending | running | done | failed | skipped`
  - UNIQUE(study_id, name)
- `artifacts(id, study_id, step_name, path, kind, sha256, bytes, meta_json, created_at)`
  - references on-disk files (downloads, intermediate `.npy`/`.fif`, plots) — **never** blobs in the DB
- `findings(id, study_id, step_name, claim, verdict, score, evidence_json, created_at)`
  - the scientific output: claim + verdict (`supported|refuted|inconclusive`) + evidence

API (all idempotent / upsert where sensible): `create_study`, `get_study`,
`list_studies`, `add_steps(plan)`, `set_step_status`, `record_step_result`,
`add_artifact`, `add_finding`, `get_findings`, `study_summary`.

### `matilde_plugin/engine/pipeline.py` — resumable runner

- `Step = (name: str, fn: Callable[[StepContext], StepResult])`
- `StepContext` carries the store, study_id, results of prior steps, and injected
  I/O handles (so steps are testable without network/fs side effects).
- `StepResult` = `{data: dict, artifacts: [...], findings: [...]}`.
- `run(store, study_id, steps, *, resume=True)`:
  - for each step in order: if its stored status is `done`, **skip** (resume);
    else mark `running`, call `fn(ctx)`, persist result + artifacts + findings,
    mark `done`; on exception mark `failed`, record error, **stop** (study
    `blocked`/`failed`, resumable later). Returns a per-step summary.
- `resume(store, study_id, steps)` = `run(..., resume=True)` — continues from the
  first non-`done` step. Re-running a fully-done study is a no-op.
- Idempotency contract: step fns must be safe to re-run from scratch (the runner
  only guarantees done-steps are skipped, not partial-step rollback).

### Agent tools (`matilde_plugin/tools.py`)

Match the existing tool-dict + handler conventions in this file:

- `matilde_study_create(slug, title, plan)` → `{study_id}` (plan = ordered step names + params)
- `matilde_study_run(study_id)` → advances pending steps; returns status + per-step summary (so an OOM/restart mid-run is resumed by simply calling this again)
- `matilde_study_status(study_id)` → full status + findings + artifacts
- `matilde_study_list()` → recent studies

### First concrete pipeline (this PR — lightweight, proves the framework, no heavy deps)

**Bibliography-validation study**: steps `parse_refs → verify_each → summarize`,
reusing the existing citations engine. `verify_each` records one finding per
reference. Demonstrated resumability: run with the verifier failing on ref #3,
assert the study is `blocked` with refs 1–2 `done`; fix the injected verifier;
`resume`; assert it completes from ref #3 without re-verifying 1–2.

### Follow-up (separate PR — heavy data analysis)

**Data-validation study** (the MEG M100 case): steps `fetch_dataset →
preprocess → epoch → evoked → validate_finding`, each **memory-bounded**
(chunked/streamed, intermediates checkpointed as artifacts) so an OOM resumes
from the last completed step. Requires deciding the agent container memory budget
and where heavy deps (mne) are installed. Out of scope for the framework PR.

## Testing

stdlib + injected I/O. Cover: store CRUD + status transitions + persistence
across a fresh `StudyStore` instance (simulates restart); runner skip-done /
stop-on-failure / resume; the bibliography study end-to-end incl. the
fail-then-resume scenario; the agent tools' arg coercion + outputs.
