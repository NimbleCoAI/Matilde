"""Tests for the matilde_fetch_fulltext tool handler (envelope + validation).

The locator engine itself is covered in test_fulltext.py with injected I/O.
Here we test the thin handler: it validates input, calls the engine, and wraps
the result in the standard ``{success, ...}`` JSON envelope, never raising.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

import matilde_plugin.engine.fulltext as ft  # noqa: E402
from matilde_plugin.tools import _handle_fetch_fulltext  # noqa: E402


def test_handler_requires_doi():
    out = json.loads(_handle_fetch_fulltext({}))
    assert out["success"] is False
    assert "doi" in out["error"].lower()


def test_handler_envelopes_open_access_result(monkeypatch):
    fake = ft.FullTextResult(
        doi="10.1234/x", is_oa=True, oa_status="green",
        best_url="https://repo/x.pdf", pdf_url="https://repo/x.pdf",
        source="openalex", license="cc-by",
    )
    monkeypatch.setattr(ft, "find_open_access", lambda *a, **k: fake)

    out = json.loads(_handle_fetch_fulltext({"doi": "10.1234/x"}))
    assert out["success"] is True
    assert out["is_oa"] is True
    assert out["pdf_url"] == "https://repo/x.pdf"
    assert out["source"] == "openalex"
    assert "message" in out


def test_handler_reports_closed_access_plainly(monkeypatch):
    fake = ft.FullTextResult(doi="10.1234/closed", is_oa=False, oa_status="closed")
    monkeypatch.setattr(ft, "find_open_access", lambda *a, **k: fake)

    out = json.loads(_handle_fetch_fulltext({"doi": "10.1234/closed"}))
    assert out["success"] is True   # a clean "no OA copy" is a successful answer
    assert out["is_oa"] is False
    assert out["pdf_url"] == ""


def test_handler_never_raises_on_engine_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")
    monkeypatch.setattr(ft, "find_open_access", boom)

    out = json.loads(_handle_fetch_fulltext({"doi": "10.1234/x"}))
    assert out["success"] is False
    assert "fetch_fulltext failed" in out["error"]
