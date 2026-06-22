"""Tests for the first concrete pipeline: a bibliography-validation study.

Steps: parse_refs -> verify_each -> summarize, reusing the citations/parsing
engine. The verifier is INJECTED so a test can force a failure on a specific
reference, prove the study blocks with the earlier refs done, then swap in a
working verifier and resume — without re-verifying the refs that already passed.
This is the end-to-end proof of the resumability guarantee.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from matilde_plugin.engine.bibliography_study import build_steps  # noqa: E402
from matilde_plugin.engine.pipeline import run, resume  # noqa: E402
from matilde_plugin.engine.store import StudyStore  # noqa: E402

# A tiny BibTeX with three entries (all PUBLIC reference material).
BIB = """
@article{a2017, title={Attention Is All You Need}, author={Vaswani, A}, year={2017}, doi={10.48550/arXiv.1706.03762}}
@article{w1953, title={Molecular structure of nucleic acids}, author={Watson, J and Crick, F}, year={1953}, doi={10.1038/171737a0}}
@article{wakefield1998, title={Ileal-lymphoid-nodular hyperplasia}, author={Wakefield, A}, year={1998}, doi={10.1016/S0140-6736(97)11096-0}}
"""


def _ok_verifier(ref):
    """A fake verifier: every ref is 'supported'. Records which refs it saw."""
    return {"verdict": "supported", "score": 0.9,
            "claim": f"reference exists: {ref.title or ref.doi}",
            "evidence": {"doi": ref.doi}}


def _failing_on_third(seen):
    """Returns a verifier that raises on the 3rd distinct ref it is asked about."""
    def verify(ref):
        seen.append(ref.doi or ref.title)
        if len(seen) >= 3:
            raise RuntimeError("verifier provider error on ref #3")
        return {"verdict": "supported", "score": 0.9,
                "claim": f"reference exists: {ref.title or ref.doi}",
                "evidence": {"doi": ref.doi}}
    return verify


@pytest.fixture()
def store(tmp_path):
    return StudyStore(str(tmp_path / "studies.db"))


def test_happy_path_records_a_finding_per_reference(store):
    sid = store.create_study(slug="bib", title="Bib",
                             plan=["parse_refs", "verify_each", "summarize"])
    steps = build_steps(bibtex=BIB, verifier=_ok_verifier)
    summary = run(store, sid, steps)

    assert store.get_study(sid)["status"] == "done"
    findings = store.get_findings(sid)
    assert len(findings) == 3
    assert all(f["verdict"] == "supported" for f in findings)
    # summarize step produced a roll-up
    summarize_result = store.get_step(sid, "summarize")["result"]
    assert summarize_result["total"] == 3
    assert summarize_result["supported"] == 3


def test_fail_then_resume_does_not_reverify_done_refs(store):
    sid = store.create_study(slug="bib", title="Bib",
                             plan=["parse_refs", "verify_each", "summarize"])

    # --- First pass: verifier fails on ref #3 ---
    seen = []
    failing_steps = build_steps(bibtex=BIB, verifier=_failing_on_third(seen))
    run(store, sid, failing_steps)

    # parse_refs done; verify_each failed; study resumable.
    assert store.get_step(sid, "parse_refs")["status"] == "done"
    assert store.get_step(sid, "verify_each")["status"] == "failed"
    assert store.get_step(sid, "summarize")["status"] == "pending"
    assert store.get_study(sid)["status"] in ("blocked", "failed")
    # Refs 1-2 were verified and persisted as findings before the failure.
    findings_after_fail = store.get_findings(sid)
    assert len(findings_after_fail) == 2

    # --- Second pass: swap in a working verifier and resume ---
    reverified = []

    def working(ref):
        reverified.append(ref.doi or ref.title)
        return _ok_verifier(ref)

    fixed_steps = build_steps(bibtex=BIB, verifier=working)
    resume(store, sid, fixed_steps)

    # Study completes.
    assert store.get_study(sid)["status"] == "done"
    # parse_refs was NOT re-run (it was done) — verifier only saw the unfinished refs.
    # Refs 1-2 already had findings; only ref #3 (and any after) get verified now.
    assert len(reverified) == 1
    findings = store.get_findings(sid)
    assert len(findings) == 3
