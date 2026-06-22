"""Offline tests for the study-pipeline agent tools.

Mirrors test_plugin_tools.py: loads the plugin, checks the new tools register,
coerce args, and return well-formed JSON envelopes. The db path is injected via
MATILDE_STUDY_DB so tests never touch the real engagements dir.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def _load_plugin():
    path = os.path.join(ROOT, "matilde_plugin", "__init__.py")
    spec = importlib.util.spec_from_file_location("matilde_plugin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plugin_registers_study_tools():
    plugin = _load_plugin()
    names = [t[0] for t in plugin._TOOLS]
    for expected in ("matilde_study_create", "matilde_study_run",
                     "matilde_study_status", "matilde_study_list"):
        assert expected in names


def test_study_create_requires_slug(monkeypatch, tmp_path):
    plugin = _load_plugin()
    monkeypatch.setenv("MATILDE_STUDY_DB", str(tmp_path / "s.db"))
    out = json.loads(plugin._handle_study_create({}))
    assert out["success"] is False


def test_study_create_returns_study_id(monkeypatch, tmp_path):
    plugin = _load_plugin()
    monkeypatch.setenv("MATILDE_STUDY_DB", str(tmp_path / "s.db"))
    out = json.loads(plugin._handle_study_create(
        {"slug": "bib", "title": "Bib", "plan": ["parse_refs", "verify_each"]}))
    assert out["success"] is True
    assert isinstance(out["study_id"], int)


def test_study_create_coerces_comma_separated_plan(monkeypatch, tmp_path):
    plugin = _load_plugin()
    monkeypatch.setenv("MATILDE_STUDY_DB", str(tmp_path / "s.db"))
    out = json.loads(plugin._handle_study_create(
        {"slug": "p", "title": "P", "plan": "a, b, c"}))
    assert out["success"] is True
    status = json.loads(plugin._handle_study_status({"study_id": out["study_id"]}))
    assert [s["name"] for s in status["steps"]] == ["a", "b", "c"]


def test_study_status_requires_id(monkeypatch, tmp_path):
    plugin = _load_plugin()
    monkeypatch.setenv("MATILDE_STUDY_DB", str(tmp_path / "s.db"))
    out = json.loads(plugin._handle_study_status({}))
    assert out["success"] is False


def test_study_status_unknown_id_errors(monkeypatch, tmp_path):
    plugin = _load_plugin()
    monkeypatch.setenv("MATILDE_STUDY_DB", str(tmp_path / "s.db"))
    out = json.loads(plugin._handle_study_status({"study_id": 9999}))
    assert out["success"] is False


def test_study_list_returns_created_studies(monkeypatch, tmp_path):
    plugin = _load_plugin()
    monkeypatch.setenv("MATILDE_STUDY_DB", str(tmp_path / "s.db"))
    plugin._handle_study_create({"slug": "one", "title": "One", "plan": ["a"]})
    plugin._handle_study_create({"slug": "two", "title": "Two", "plan": ["a"]})
    out = json.loads(plugin._handle_study_list({}))
    assert out["success"] is True
    slugs = [s["slug"] for s in out["studies"]]
    assert "one" in slugs and "two" in slugs


def _strict_loads(s: str):
    """json.loads that REJECTS non-finite literals (NaN/Infinity), like the
    strict JSON parsers a tool envelope is fed into downstream."""
    def _reject(tok):
        raise ValueError(f"non-finite JSON literal {tok!r}")
    return json.loads(s, parse_constant=_reject)


def test_study_status_returns_strict_json_for_completed_study(monkeypatch, tmp_path):
    """Regression: a completed study's status must be a structured, strictly
    JSON-parseable result — not an error envelope. A live measure_peak can yield
    a non-finite float (NaN/Infinity) in a finding's evidence; json.dumps emits
    those as bare NaN/Infinity, which is invalid JSON and made the framework
    treat study_status as an error. The envelope must serialize them safely."""
    plugin = _load_plugin()
    monkeypatch.setenv("MATILDE_STUDY_DB", str(tmp_path / "s.db"))
    from matilde_plugin.engine.store import StudyStore

    created = json.loads(plugin._handle_study_create(
        {"slug": "meg-nan", "title": "MEG NaN", "plan": ["validate_finding"]}))
    sid = created["study_id"]

    # Simulate what a real (lazy-mne) run can record: a finding whose evidence
    # holds a non-finite float (e.g. a degenerate amplitude/latency).
    store = StudyStore(str(tmp_path / "s.db"))
    store.set_step_status(sid, "validate_finding", "done")
    store.add_finding(
        sid, "validate_finding",
        claim="auditory M100 peak falls within 80-120 ms",
        verdict="supported",
        evidence={"latency_ms": 120.0, "amplitude": float("nan"),
                  "extra": float("inf")})
    store.set_study_status(sid, "done")
    store.close()

    raw = plugin._handle_study_status({"study_id": sid})
    # Must parse under a STRICT parser (no bare NaN/Infinity tokens).
    out = _strict_loads(raw)
    assert out["success"] is True, out
    assert "error" not in out
    assert out["status"] == "done"
    assert out["finding_count"] == 1
    # The non-finite values are represented safely (None), not as bare NaN.
    ev = out["findings"][0]["evidence"]
    assert ev["amplitude"] is None
    assert ev["extra"] is None
    assert ev["latency_ms"] == 120.0


def test_study_run_advances_and_is_resumable(monkeypatch, tmp_path):
    """End-to-end through the tools using the bibliography study. Coerces a string
    id, runs to completion, and a second run is a no-op (resume of a done study)."""
    plugin = _load_plugin()
    monkeypatch.setenv("MATILDE_STUDY_DB", str(tmp_path / "s.db"))
    bib = ("@article{w1953, title={Molecular structure of nucleic acids}, "
           "author={Watson, J}, year={1953}, doi={10.1038/171737a0}}")
    created = json.loads(plugin._handle_study_create({
        "slug": "bibrun", "title": "Bib run",
        "plan": ["parse_refs", "verify_each", "summarize"],
        "kind": "bibliography", "bibtex": bib,
    }))
    sid = created["study_id"]
    # study_run accepts a string id (arg coercion).
    out = json.loads(plugin._handle_study_run({"study_id": str(sid)}))
    assert out["success"] is True
    assert out["status"] == "done"
    status = json.loads(plugin._handle_study_status({"study_id": sid}))
    assert status["finding_count"] == 1


def test_golden_meg_validation_runs_offline_through_tools(monkeypatch, tmp_path):
    """The self-demonstrating recipe (#14): create + run kind='golden_meg_validation'
    end-to-end through the tools, no mne / numpy / download, yielding a supported
    finding. This is the live path the agent imitates."""
    plugin = _load_plugin()
    monkeypatch.setenv("MATILDE_STUDY_DB", str(tmp_path / "s.db"))
    created = json.loads(plugin._handle_study_create({
        "slug": "golden", "title": "Golden recipe",
        "kind": "golden_meg_validation",
    }))
    assert created["success"] is True
    sid = created["study_id"]
    out = json.loads(plugin._handle_study_run({"study_id": sid}))
    assert out["success"] is True
    assert out["status"] == "done"
    assert "mne" not in sys.modules and "numpy" not in sys.modules
    status = json.loads(plugin._handle_study_status({"study_id": sid}))
    assert status["finding_count"] == 1
