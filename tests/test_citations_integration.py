"""Live integration tests — hit the real Crossref API.

Skipped unless ``MATILDE_LIVE=1`` so the default suite stays offline and fast.
Run with::

    MATILDE_LIVE=1 python3 -m pytest tests/test_citations_integration.py -q

These guard the assumptions the offline fixtures encode (Crossref field shapes,
real retraction signals) against API drift.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from matilde_plugin.engine.citations import (  # noqa: E402
    Reference,
    check_retraction,
    default_fetch,
    verify_reference,
)

LIVE = os.environ.get("MATILDE_LIVE") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="set MATILDE_LIVE=1 to run live API tests")


def test_live_known_retracted_paper_is_flagged():
    # Wakefield et al. 1998 (Lancet), retracted 2010 — the canonical example.
    res = check_retraction("10.1016/S0140-6736(97)11096-0", fetch=default_fetch)
    assert res.status == "fail", res.detail


def test_live_crossref_journal_doi_verifies():
    # A real Crossref-registered journal article (Watson & Crick, Nature 1953).
    ref = Reference(
        title="Molecular structure of nucleic acids",
        authors=["Watson", "Crick"],
        year=1953,
        doi="10.1038/171737a0",
    )
    result = verify_reference(ref)  # real network
    assert result.existence.status == "pass"
    assert result.retraction.status in {"pass", "unknown"}
    assert result.verdict in {"verified", "warnings"}


def test_live_arxiv_datacite_doi_falls_back_to_openalex():
    # arXiv DOIs aren't in Crossref — this guards the OpenAlex existence fallback
    # so a real preprint is never mislabeled "fabricated".
    ref = Reference(
        title="Attention Is All You Need",
        authors=["Vaswani", "Shazeer"],
        year=2017,
        doi="10.48550/arXiv.1706.03762",
    )
    result = verify_reference(ref)  # real network
    assert result.existence.status == "pass"
    # Resolved by a non-Crossref authority (OpenAlex or DataCite) — never "fabricated".
    assert result.existence.evidence.get("source") in {"openalex", "datacite"}
    assert result.verdict in {"verified", "warnings"}
