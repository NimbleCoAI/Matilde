"""Offline smoke tests for the Matilde Hermes plugin wiring.

Verifies the plugin loads, exposes the expected tools, gates correctly, coerces
arguments, and returns well-formed JSON envelopes on bad input — all without
touching the network (the live verification path is covered by
test_citations_integration.py).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def _load_plugin():
    path = os.path.join(ROOT, "hermes-plugin", "__init__.py")
    spec = importlib.util.spec_from_file_location("matilde_plugin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_plugin_loads_and_registers_three_tools():
    plugin = _load_plugin()
    names = [t[0] for t in plugin._TOOLS]
    assert names == [
        "matilde_verify_citation",
        "matilde_verify_bibliography",
        "matilde_check_retraction",
    ]


def test_register_calls_ctx_for_each_tool():
    plugin = _load_plugin()
    calls = []

    class Ctx:
        def register_tool(self, **kw):
            calls.append(kw)

    plugin.register(Ctx())
    assert len(calls) == 3
    assert all(c["toolset"] == "matilde" for c in calls)
    assert all(callable(c["handler"]) and callable(c["check_fn"]) for c in calls)
    # schema name must match the registered tool name
    assert all(c["name"] == c["schema"]["name"] for c in calls)


def test_check_available_true_when_engine_imports():
    plugin = _load_plugin()
    assert plugin._check_available() is True


def test_verify_citation_requires_doi_or_title():
    plugin = _load_plugin()
    out = json.loads(plugin._handle_verify_citation({}))
    assert out["success"] is False
    assert "doi" in out["error"] or "title" in out["error"]


def test_verify_bibliography_rejects_non_list():
    plugin = _load_plugin()
    out = json.loads(plugin._handle_verify_bibliography({"references": "nope"}))
    assert out["success"] is False


def test_check_retraction_requires_doi():
    plugin = _load_plugin()
    out = json.loads(plugin._handle_check_retraction({}))
    assert out["success"] is False


def test_reference_from_args_coerces_string_authors_and_year():
    plugin = _load_plugin()
    ref = plugin._tools_mod._reference_from_args(
        {"title": "X", "authors": "Vaswani; Shazeer", "year": "2017", "doi": "10.1/x"}
    )
    assert ref.authors == ["Vaswani", "Shazeer"]
    assert ref.year == 2017
    assert ref.doi == "10.1/x"
