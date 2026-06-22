"""Resumable study runner — checkpoints each step into a ``StudyStore``.

A study is an ordered list of :class:`Step`\\s. The runner walks them in order:
a step whose stored status is already ``done`` is **skipped** (resume); otherwise
it is marked ``running``, its ``fn`` is called, its result + artifacts + findings
are persisted, and it is marked ``done``. On exception the step is marked
``failed`` (with the error), the study is marked ``blocked``, and the run **stops**
— leaving everything before it ``done`` and the study resumable later. This is the
durability contract: an OOM or container rebuild mid-run is recovered by simply
calling ``run``/``resume`` again on the same store.

Pure and injected: a :class:`Step`'s ``fn`` receives a :class:`StepContext`
carrying the store, the study id, and the results of prior steps, so steps are
unit-testable with in-memory fakes (no network/fs needed).

Idempotency contract: the runner only guarantees *done steps are skipped*, not
partial-step rollback. A step that does internal sub-work (e.g. verifying N refs)
must itself be safe to re-run from scratch — typically by checking the store for
what it already persisted and skipping that (see ``bibliography_study``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .store import StudyStore


@dataclass
class StepResult:
    """What a step produces. All optional — a step may only record findings."""

    data: dict = field(default_factory=dict)
    artifacts: List[dict] = field(default_factory=list)
    findings: List[dict] = field(default_factory=list)


@dataclass
class StepContext:
    """Handle passed to a step's ``fn``: the store, the study, and prior results."""

    store: StudyStore
    study_id: int
    step_name: str
    results: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Step:
    name: str
    fn: Callable[[StepContext], StepResult]


def run(store: StudyStore, study_id: int, steps: List[Step], *,
        resume: bool = True) -> dict:
    """Execute *steps* in order against *study_id*, persisting after each.

    Returns a summary dict: ``{study_id, status, steps: [...], failed_step}``.
    Done steps are skipped when ``resume`` is True (the default).
    """
    store.add_steps(study_id, [s.name for s in steps])

    # Carry forward results of steps already done (so a resumed step can read them).
    prior: Dict[str, Any] = {}
    for s in store.get_steps(study_id):
        if s["status"] == "done" and s["result"] is not None:
            prior[s["name"]] = s["result"]

    store.set_study_status(study_id, "running")
    per_step: List[dict] = []
    failed_step: Optional[str] = None

    for step in steps:
        stored = store.get_step(study_id, step.name)
        if resume and stored is not None and stored["status"] == "done":
            per_step.append({"name": step.name, "status": "done", "skipped": True})
            continue

        store.set_step_status(study_id, step.name, "running")
        ctx = StepContext(store=store, study_id=study_id,
                          step_name=step.name, results=dict(prior))
        try:
            result = step.fn(ctx)
        except Exception as exc:  # stop, leave resumable
            store.set_step_status(study_id, step.name, "failed",
                                  error=f"{type(exc).__name__}: {exc}")
            store.set_study_status(study_id, "blocked")
            per_step.append({"name": step.name, "status": "failed",
                             "error": f"{type(exc).__name__}: {exc}"})
            failed_step = step.name
            return {"study_id": study_id, "status": "blocked",
                    "steps": per_step, "failed_step": failed_step}

        result = result or StepResult()
        store.record_step_result(study_id, step.name, result.data)
        for art in result.artifacts:
            store.add_artifact(
                study_id, step.name,
                path=art.get("path", ""), kind=art.get("kind", ""),
                sha256=art.get("sha256", ""), bytes=art.get("bytes"),
                meta=art.get("meta"))
        for fnd in result.findings:
            store.add_finding(
                study_id, step.name,
                claim=fnd.get("claim", ""), verdict=fnd.get("verdict", ""),
                score=fnd.get("score"), evidence=fnd.get("evidence"))
        store.set_step_status(study_id, step.name, "done")
        prior[step.name] = result.data
        per_step.append({"name": step.name, "status": "done"})

    store.set_study_status(study_id, "done")
    return {"study_id": study_id, "status": "done",
            "steps": per_step, "failed_step": None}


def resume(store: StudyStore, study_id: int, steps: List[Step]) -> dict:
    """Continue a study from its first non-``done`` step. A fully-done study is a
    no-op. Equivalent to ``run(..., resume=True)``."""
    return run(store, study_id, steps, resume=True)
