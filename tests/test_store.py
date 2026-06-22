"""Tests for the StudyStore — durable, checkpointed analysis state (SQLite).

All I/O is a temp db path (injected), so these run offline and deterministically.
The load-bearing test is ``test_state_survives_fresh_store_instance``: it proves
the store's "survives container rebuild" guarantee by opening a NEW StudyStore on
the same db file and reading back everything the first instance wrote.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from matilde_plugin.engine.store import StudyStore  # noqa: E402


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "studies.db")


def test_create_and_get_study(db_path):
    store = StudyStore(db_path)
    sid = store.create_study(slug="bib-check", title="Bibliography check",
                             plan=["parse_refs", "verify_each", "summarize"])
    assert isinstance(sid, int)
    study = store.get_study(sid)
    assert study["slug"] == "bib-check"
    assert study["title"] == "Bibliography check"
    assert study["status"] == "created"
    assert study["plan"] == ["parse_refs", "verify_each", "summarize"]
    assert study["created_at"]
    assert study["updated_at"]


def test_create_study_is_idempotent_on_slug(db_path):
    store = StudyStore(db_path)
    sid1 = store.create_study(slug="dup", title="First", plan=["a"])
    sid2 = store.create_study(slug="dup", title="Second", plan=["a", "b"])
    # Same slug returns the same study (upsert), not a duplicate row.
    assert sid1 == sid2
    assert len(store.list_studies()) == 1


def test_add_steps_creates_pending_steps_in_order(db_path):
    store = StudyStore(db_path)
    sid = store.create_study(slug="s", title="S", plan=[])
    store.add_steps(sid, ["one", "two", "three"])
    steps = store.get_steps(sid)
    assert [s["name"] for s in steps] == ["one", "two", "three"]
    assert [s["idx"] for s in steps] == [0, 1, 2]
    assert all(s["status"] == "pending" for s in steps)


def test_add_steps_is_idempotent(db_path):
    store = StudyStore(db_path)
    sid = store.create_study(slug="s", title="S", plan=[])
    store.add_steps(sid, ["one", "two"])
    store.add_steps(sid, ["one", "two", "three"])  # re-add + extend
    steps = store.get_steps(sid)
    assert [s["name"] for s in steps] == ["one", "two", "three"]


def test_set_step_status_transitions(db_path):
    store = StudyStore(db_path)
    sid = store.create_study(slug="s", title="S", plan=[])
    store.add_steps(sid, ["one"])
    store.set_step_status(sid, "one", "running")
    assert store.get_step(sid, "one")["status"] == "running"
    store.set_step_status(sid, "one", "done")
    assert store.get_step(sid, "one")["status"] == "done"
    store.set_step_status(sid, "one", "failed", error="boom")
    step = store.get_step(sid, "one")
    assert step["status"] == "failed"
    assert step["error"] == "boom"


def test_record_step_result_persists_json(db_path):
    store = StudyStore(db_path)
    sid = store.create_study(slug="s", title="S", plan=[])
    store.add_steps(sid, ["one"])
    store.record_step_result(sid, "one", {"count": 3, "items": ["a", "b"]})
    step = store.get_step(sid, "one")
    assert step["result"] == {"count": 3, "items": ["a", "b"]}


def test_add_and_get_artifact(db_path):
    store = StudyStore(db_path)
    sid = store.create_study(slug="s", title="S", plan=[])
    store.add_steps(sid, ["one"])
    store.add_artifact(sid, "one", path="/data/out.npy", kind="array",
                       sha256="abc", bytes=128, meta={"shape": [4]})
    arts = store.get_artifacts(sid)
    assert len(arts) == 1
    a = arts[0]
    assert a["path"] == "/data/out.npy"
    assert a["kind"] == "array"
    assert a["sha256"] == "abc"
    assert a["bytes"] == 128
    assert a["meta"] == {"shape": [4]}


def test_add_and_get_finding(db_path):
    store = StudyStore(db_path)
    sid = store.create_study(slug="s", title="S", plan=[])
    store.add_steps(sid, ["verify"])
    store.add_finding(sid, "verify", claim="ref #1 exists", verdict="supported",
                      score=0.95, evidence={"doi": "10.1/x"})
    findings = store.get_findings(sid)
    assert len(findings) == 1
    f = findings[0]
    assert f["claim"] == "ref #1 exists"
    assert f["verdict"] == "supported"
    assert f["score"] == 0.95
    assert f["evidence"] == {"doi": "10.1/x"}


def test_study_summary_aggregates_steps_and_findings(db_path):
    store = StudyStore(db_path)
    sid = store.create_study(slug="s", title="S", plan=["a", "b"])
    store.add_steps(sid, ["a", "b"])
    store.set_step_status(sid, "a", "done")
    store.add_finding(sid, "a", claim="c", verdict="supported", score=1.0)
    summary = store.study_summary(sid)
    assert summary["study"]["slug"] == "s"
    assert summary["step_status_counts"]["done"] == 1
    assert summary["step_status_counts"]["pending"] == 1
    assert summary["finding_count"] == 1
    assert len(summary["findings"]) == 1
    assert any(s["name"] == "a" and s["status"] == "done" for s in summary["steps"])


def test_list_studies_returns_recent_first(db_path):
    store = StudyStore(db_path)
    a = store.create_study(slug="a", title="A", plan=[])
    b = store.create_study(slug="b", title="B", plan=[])
    studies = store.list_studies()
    ids = [s["id"] for s in studies]
    # most-recent-first ordering
    assert ids.index(b) < ids.index(a)


def test_get_study_missing_returns_none(db_path):
    store = StudyStore(db_path)
    assert store.get_study(9999) is None


# --- The load-bearing guarantee: state survives a fresh StudyStore instance ---

def test_state_survives_fresh_store_instance(db_path):
    """Simulates a container rebuild: a brand-new StudyStore on the same db file
    must see everything the first instance committed."""
    store1 = StudyStore(db_path)
    sid = store1.create_study(slug="durable", title="Durable",
                              plan=["parse", "verify"])
    store1.add_steps(sid, ["parse", "verify"])
    store1.set_step_status(sid, "parse", "done")
    store1.record_step_result(sid, "parse", {"n": 2})
    store1.add_finding(sid, "verify", claim="x", verdict="supported", score=0.9)
    del store1  # drop the connection — simulate process death / rebuild

    store2 = StudyStore(db_path)  # fresh instance, same file
    study = store2.get_study(sid)
    assert study is not None
    assert study["slug"] == "durable"
    assert store2.get_step(sid, "parse")["status"] == "done"
    assert store2.get_step(sid, "parse")["result"] == {"n": 2}
    findings = store2.get_findings(sid)
    assert len(findings) == 1
    assert findings[0]["claim"] == "x"


def test_wal_mode_is_enabled(db_path):
    store = StudyStore(db_path)
    mode = store._conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert mode.lower() == "wal"
