"""Tests for the resumable pipeline runner.

Steps are in-memory fakes with side-effect counters, so we can prove the runner
(a) skips already-done steps on resume and (b) stops on a failing step leaving the
study resumable, then continues from the first non-done step on resume — WITHOUT
re-running the steps that already completed.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from matilde_plugin.engine.pipeline import Step, StepResult, run, resume  # noqa: E402
from matilde_plugin.engine.store import StudyStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return StudyStore(str(tmp_path / "studies.db"))


def _counter_step(name, calls, *, data=None, fail=False):
    def fn(ctx):
        calls.append(name)
        if fail:
            raise RuntimeError(f"{name} blew up")
        return StepResult(data=data or {"step": name})
    return Step(name=name, fn=fn)


def test_run_executes_all_steps_and_marks_done(store):
    sid = store.create_study(slug="s", title="S", plan=[])
    calls = []
    steps = [_counter_step("a", calls), _counter_step("b", calls)]
    summary = run(store, sid, steps)
    assert calls == ["a", "b"]
    assert store.get_step(sid, "a")["status"] == "done"
    assert store.get_step(sid, "b")["status"] == "done"
    assert store.get_study(sid)["status"] == "done"
    assert [s["name"] for s in summary["steps"]] == ["a", "b"]


def test_run_persists_step_data_artifacts_and_findings(store):
    sid = store.create_study(slug="s", title="S", plan=[])

    def fn(ctx):
        return StepResult(
            data={"k": "v"},
            artifacts=[{"path": "/x", "kind": "blob", "bytes": 1}],
            findings=[{"claim": "c", "verdict": "supported", "score": 1.0}],
        )

    run(store, sid, [Step(name="only", fn=fn)])
    assert store.get_step(sid, "only")["result"] == {"k": "v"}
    assert len(store.get_artifacts(sid)) == 1
    assert store.get_findings(sid)[0]["claim"] == "c"


def test_run_skips_already_done_steps(store):
    sid = store.create_study(slug="s", title="S", plan=[])
    store.add_steps(sid, ["a", "b"])
    store.set_step_status(sid, "a", "done")  # pretend 'a' already ran
    calls = []
    steps = [_counter_step("a", calls), _counter_step("b", calls)]
    run(store, sid, steps)
    assert calls == ["b"]  # 'a' was skipped


def test_run_stops_on_failure_and_leaves_study_resumable(store):
    sid = store.create_study(slug="s", title="S", plan=[])
    calls = []
    steps = [
        _counter_step("a", calls),
        _counter_step("b", calls, fail=True),
        _counter_step("c", calls),
    ]
    summary = run(store, sid, steps)
    assert calls == ["a", "b"]  # stopped at b; c never ran
    assert store.get_step(sid, "a")["status"] == "done"
    assert store.get_step(sid, "b")["status"] == "failed"
    assert store.get_step(sid, "c")["status"] == "pending"
    assert store.get_study(sid)["status"] in ("blocked", "failed")
    assert summary["failed_step"] == "b"


def test_resume_continues_from_first_non_done_without_rerunning(store):
    sid = store.create_study(slug="s", title="S", plan=[])

    # First pass: 'b' fails.
    calls1 = []
    failing = [
        _counter_step("a", calls1),
        _counter_step("b", calls1, fail=True),
        _counter_step("c", calls1),
    ]
    run(store, sid, failing)
    assert calls1 == ["a", "b"]

    # Second pass: swap in a WORKING 'b'. Resume must NOT re-run 'a'.
    calls2 = []
    fixed = [
        _counter_step("a", calls2),
        _counter_step("b", calls2),  # now succeeds
        _counter_step("c", calls2),
    ]
    resume(store, sid, fixed)
    assert calls2 == ["b", "c"]  # 'a' skipped (already done), continues from b
    assert store.get_study(sid)["status"] == "done"
    assert store.get_step(sid, "c")["status"] == "done"


def test_resume_of_completed_study_is_noop(store):
    sid = store.create_study(slug="s", title="S", plan=[])
    calls = []
    steps = [_counter_step("a", calls), _counter_step("b", calls)]
    run(store, sid, steps)
    assert calls == ["a", "b"]
    calls.clear()
    resume(store, sid, steps)
    assert calls == []  # nothing re-ran
    assert store.get_study(sid)["status"] == "done"


def test_step_context_exposes_prior_results(store):
    sid = store.create_study(slug="s", title="S", plan=[])
    seen = {}

    def a(ctx):
        return StepResult(data={"value": 42})

    def b(ctx):
        seen["prior"] = ctx.results.get("a")
        return StepResult(data={})

    run(store, sid, [Step(name="a", fn=a), Step(name="b", fn=b)])
    assert seen["prior"] == {"value": 42}
