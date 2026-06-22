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
