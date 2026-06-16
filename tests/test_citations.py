"""Tests for the verifiable-citations engine (axes 1-3).

These tests exercise the pure verification logic with *injected* I/O — no
network. A fake ``fetch`` maps request URLs to canned JSON; a fake ``http_head``
maps URLs to status codes. This keeps the suite deterministic and fast, and
lets us assert exact verdicts for known inputs.

Live integration tests (real Crossref/network) live in
``test_citations_integration.py`` and are skipped unless MATILDE_LIVE=1.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from engine.citations import (  # noqa: E402
    AxisResult,
    Reference,
    VerificationResult,
    _openalex_to_record,
    author_overlap,
    check_retraction,
    check_url_liveness,
    check_metadata_match,
    title_similarity,
    verify_existence,
    verify_reference,
)


# A canonical OpenAlex "work" for an arXiv-registered (DataCite) paper that
# Crossref does NOT have — the case that exposed the false-fabrication bug.
OPENALEX_ATTENTION = {
    "id": "https://openalex.org/W2963403868",
    "doi": "https://doi.org/10.48550/arxiv.1706.03762",
    "display_name": "Attention Is All You Need",
    "publication_year": 2017,
    "is_retracted": False,
    "authorships": [
        {"author": {"display_name": "Ashish Vaswani"}},
        {"author": {"display_name": "Noam Shazeer"}},
    ],
    "primary_location": {"source": {"display_name": "arXiv"}},
}

# A canonical DataCite response for the same arXiv paper.
DATACITE_ATTENTION = {
    "data": {
        "id": "10.48550/arxiv.1706.03762",
        "attributes": {
            "doi": "10.48550/arxiv.1706.03762",
            "titles": [{"title": "Attention Is All You Need"}],
            "publicationYear": 2017,
            "creators": [
                {"name": "Vaswani, Ashish", "familyName": "Vaswani"},
                {"name": "Shazeer, Noam", "familyName": "Shazeer"},
            ],
        },
    }
}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def make_fetch(mapping):
    """Return a fetch(url)->dict that looks up url in mapping or raises."""
    def _fetch(url: str, **_):
        for key, value in mapping.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value
        raise LookupError(f"no fake response for {url}")
    return _fetch


def make_head(mapping, default=None):
    """Return http_head(url)->(status, final_url)."""
    def _head(url: str, **_):
        for key, value in mapping.items():
            if key in url:
                return value
        return (default, url)
    return _head


# A canonical Crossref "message" for a real, clean paper.
ATTENTION_PAPER = {
    "message": {
        "DOI": "10.5555/attention",
        "title": ["Attention Is All You Need"],
        "author": [
            {"family": "Vaswani", "given": "Ashish"},
            {"family": "Shazeer", "given": "Noam"},
        ],
        "published": {"date-parts": [[2017]]},
        "container-title": ["NeurIPS"],
    }
}


# ---------------------------------------------------------------------------
# String similarity primitives
# ---------------------------------------------------------------------------

def test_title_similarity_identical_is_one():
    assert title_similarity("Attention Is All You Need", "Attention Is All You Need") == 1.0


def test_title_similarity_is_case_and_punctuation_insensitive():
    assert title_similarity("Attention Is All You Need!", "attention is all you need") >= 0.99


def test_title_similarity_different_titles_low():
    assert title_similarity("Attention Is All You Need", "A Survey of Llamas") < 0.5


def test_author_overlap_full():
    assert author_overlap(["Vaswani", "Shazeer"], ["Ashish Vaswani", "Noam Shazeer"]) == 1.0


def test_author_overlap_partial():
    # one of two surnames matches
    assert author_overlap(["Vaswani", "Smith"], ["Ashish Vaswani"]) == pytest.approx(0.5)


def test_author_overlap_empty_is_unknown_zero():
    assert author_overlap([], ["Vaswani"]) == 0.0


# ---------------------------------------------------------------------------
# Axis 1: existence
# ---------------------------------------------------------------------------

def test_existence_by_doi_found():
    ref = Reference(title="Attention Is All You Need", doi="10.5555/attention")
    fetch = make_fetch({"works/10.5555/attention": ATTENTION_PAPER})
    res = verify_existence(ref, fetch=fetch)
    assert isinstance(res, AxisResult)
    assert res.status == "pass"
    assert res.evidence.get("record") is not None


def test_existence_doi_missing_in_crossref_falls_back_to_openalex():
    # arXiv/DataCite DOIs are NOT in Crossref. Existence must fall back to OpenAlex
    # before declaring a real paper "fabricated".
    ref = Reference(title="Attention Is All You Need", doi="10.48550/arXiv.1706.03762")
    fetch = make_fetch({
        "api.crossref.org/works/": LookupError("404"),       # Crossref miss
        "api.openalex.org/works/": OPENALEX_ATTENTION,        # OpenAlex hit
    })
    res = verify_existence(ref, fetch=fetch)
    assert res.status == "pass"
    assert res.evidence.get("record", {}).get("_source") == "openalex"


def test_existence_doi_resolves_via_datacite_when_crossref_and_openalex_miss():
    # arXiv 10.48550/* DOIs are registered with DataCite, not Crossref, and are
    # not always in OpenAlex — DataCite is the authoritative final fallback.
    ref = Reference(title="Attention Is All You Need", doi="10.48550/arXiv.1706.03762")
    fetch = make_fetch({
        "api.crossref.org/works/": LookupError("404"),
        "api.openalex.org/works/": LookupError("404"),
        "api.datacite.org/dois/": DATACITE_ATTENTION,
    })
    res = verify_existence(ref, fetch=fetch)
    assert res.status == "pass"
    assert res.evidence.get("record", {}).get("_source") == "datacite"


def test_existence_by_doi_not_found_in_any_authority_is_fail():
    ref = Reference(title="Totally Fabricated", doi="10.9999/nope")
    fetch = make_fetch({
        "api.crossref.org/works/": LookupError("404"),
        "api.openalex.org/works/": LookupError("404"),
        "api.datacite.org/dois/": LookupError("404"),
    })
    res = verify_existence(ref, fetch=fetch)
    assert res.status == "fail"  # absent from ALL authorities = strong fabrication signal


def test_existence_by_title_when_no_doi():
    ref = Reference(title="Attention Is All You Need")
    fetch = make_fetch({"query.bibliographic": {"message": {"items": [ATTENTION_PAPER["message"]]}}})
    res = verify_existence(ref, fetch=fetch)
    assert res.status == "pass"
    assert res.evidence.get("record", {}).get("DOI") == "10.5555/attention"


def test_existence_by_title_no_match_is_unknown():
    # title search returns items but none similar enough -> unknown, not fail
    ref = Reference(title="A Paper That Does Not Exist At All")
    fetch = make_fetch({"query.bibliographic": {"message": {"items": [ATTENTION_PAPER["message"]]}}})
    res = verify_existence(ref, fetch=fetch)
    assert res.status == "unknown"


# ---------------------------------------------------------------------------
# Axis 2: metadata match
# ---------------------------------------------------------------------------

def test_metadata_match_pass():
    ref = Reference(title="Attention Is All You Need", authors=["Vaswani"], year=2017)
    res = check_metadata_match(ref, ATTENTION_PAPER["message"])
    assert res.status == "pass"


def test_metadata_match_year_mismatch_warns():
    ref = Reference(title="Attention Is All You Need", authors=["Vaswani"], year=2021)
    res = check_metadata_match(ref, ATTENTION_PAPER["message"])
    assert res.status in {"warn", "fail"}
    assert "year" in res.detail.lower()


def test_metadata_match_wrong_title_fails():
    ref = Reference(title="Something Completely Different", authors=["Vaswani"], year=2017)
    res = check_metadata_match(ref, ATTENTION_PAPER["message"])
    assert res.status == "fail"


# ---------------------------------------------------------------------------
# Axis 3a: retraction
# ---------------------------------------------------------------------------

def test_retraction_clean_paper_passes():
    fetch = make_fetch({"works/10.5555/attention": ATTENTION_PAPER})
    res = check_retraction("10.5555/attention", fetch=fetch)
    assert res.status == "pass"  # pass == not retracted


def test_retraction_detected_via_update_to():
    retracted = {
        "message": {
            "DOI": "10.1234/bad",
            "title": ["A Retracted Study"],
            "update-to": [
                {"type": "retraction", "DOI": "10.1234/notice", "label": "Retraction"}
            ],
        }
    }
    fetch = make_fetch({"works/10.1234/bad": retracted})
    res = check_retraction("10.1234/bad", fetch=fetch)
    assert res.status == "fail"  # fail == IS retracted
    assert "retract" in res.detail.lower()


def test_retraction_detected_via_relation():
    retracted = {
        "message": {
            "DOI": "10.1234/bad2",
            "relation": {"is-retracted-by": [{"id": "10.1234/notice2", "id-type": "doi"}]},
        }
    }
    fetch = make_fetch({"works/10.1234/bad2": retracted})
    res = check_retraction("10.1234/bad2", fetch=fetch)
    assert res.status == "fail"


def test_retraction_detected_via_updated_by_real_shape():
    # Mirrors the REAL Crossref shape for the retracted Wakefield 1998 paper:
    # multiple `updated-by` entries — a correction AND a retraction, both sourced
    # from retraction-watch.
    retracted = {
        "message": {
            "DOI": "10.1016/s0140-6736(97)11096-0",
            "title": ["RETRACTED: Ileal-lymphoid-nodular hyperplasia"],
            "updated-by": [
                {"DOI": "10.1016/s0140-6736(04)15715-2", "type": "correction",
                 "label": "Correction", "source": "retraction-watch"},
                {"DOI": "10.1016/s0140-6736(10)60175-4", "type": "retraction",
                 "label": "Retraction", "source": "retraction-watch"},
            ],
        }
    }
    fetch = make_fetch({"works/10.1016": retracted})
    res = check_retraction("10.1016/s0140-6736(97)11096-0", fetch=fetch)
    assert res.status == "fail"
    assert "retract" in res.detail.lower()


def test_retraction_correction_only_is_not_retracted():
    # A correction (without a retraction entry) must NOT be flagged as retracted.
    corrected = {
        "message": {
            "DOI": "10.1/ok",
            "updated-by": [{"type": "correction", "label": "Correction"}],
        }
    }
    fetch = make_fetch({"works/10.1/ok": corrected})
    res = check_retraction("10.1/ok", fetch=fetch)
    assert res.status == "pass"


def test_openalex_to_record_normalizes_to_crossref_shape():
    rec = _openalex_to_record(OPENALEX_ATTENTION)
    assert rec["_source"] == "openalex"
    assert title_similarity("Attention Is All You Need", _title := rec["title"][0]) == 1.0
    assert rec["published"]["date-parts"][0][0] == 2017
    # author normalized so author_overlap works against it
    assert author_overlap(["Vaswani"], rec["author"]) == 1.0


def test_retraction_via_openalex_is_retracted_flag():
    retracted_oa = dict(OPENALEX_ATTENTION, is_retracted=True)
    rec = _openalex_to_record(retracted_oa)
    from engine.citations import _retraction_signal
    assert _retraction_signal(rec) is not None


def test_retraction_no_doi_is_unknown():
    res = check_retraction("", fetch=make_fetch({}))
    assert res.status == "unknown"


# ---------------------------------------------------------------------------
# Axis 3b: URL liveness
# ---------------------------------------------------------------------------

def test_url_liveness_live():
    head = make_head({"example.org/paper": (200, "https://example.org/paper")})
    res = check_url_liveness("https://example.org/paper", http_head=head)
    assert res.status == "pass"


def test_url_liveness_dead_no_archive_is_fail():
    head = make_head({"dead.example": (404, "https://dead.example/x")})
    fetch = make_fetch({"archive.org/wayback/available": {"archived_snapshots": {}}})
    res = check_url_liveness("https://dead.example/x", http_head=head, fetch=fetch)
    assert res.status == "fail"


def test_url_liveness_dead_but_archived_warns():
    head = make_head({"dead.example": (404, "https://dead.example/x")})
    fetch = make_fetch(
        {"archive.org/wayback/available": {"archived_snapshots": {"closest": {"available": True, "url": "http://web.archive.org/x"}}}}
    )
    res = check_url_liveness("https://dead.example/x", http_head=head, fetch=fetch)
    assert res.status == "warn"
    assert "archive" in res.detail.lower()


def test_url_liveness_empty_url_is_unknown():
    res = check_url_liveness("", http_head=make_head({}))
    assert res.status == "unknown"


# ---------------------------------------------------------------------------
# End-to-end: verify_reference
# ---------------------------------------------------------------------------

def test_verify_reference_clean_is_verified():
    ref = Reference(title="Attention Is All You Need", authors=["Vaswani"], year=2017,
                    doi="10.5555/attention", url="https://example.org/paper")
    fetch = make_fetch({"works/10.5555/attention": ATTENTION_PAPER})
    head = make_head({"example.org/paper": (200, "https://example.org/paper")})
    result = verify_reference(ref, fetch=fetch, http_head=head)
    assert isinstance(result, VerificationResult)
    assert result.verdict == "verified"
    assert result.score >= 0.8


def test_verify_reference_nonexistent_doi_is_not_found():
    ref = Reference(title="Fabricated Paper", doi="10.9999/nope")
    fetch = make_fetch({"works/10.9999/nope": LookupError("404")})
    result = verify_reference(ref, fetch=fetch, http_head=make_head({}))
    assert result.verdict == "not_found"
    assert result.score < 0.3


def test_verify_reference_retracted_overrides_to_retracted():
    retracted = {
        "message": {
            "DOI": "10.1234/bad",
            "title": ["A Retracted Study"],
            "author": [{"family": "Doe"}],
            "published": {"date-parts": [[2015]]},
            "update-to": [{"type": "retraction", "DOI": "10.1234/notice"}],
        }
    }
    ref = Reference(title="A Retracted Study", authors=["Doe"], year=2015, doi="10.1234/bad")
    fetch = make_fetch({"works/10.1234/bad": retracted})
    result = verify_reference(ref, fetch=fetch, http_head=make_head({}))
    # Even though it exists and metadata matches, a retraction dominates the verdict.
    assert result.verdict == "retracted"
    assert result.score < 0.3


def test_verify_reference_to_dict_is_json_safe():
    ref = Reference(title="Attention Is All You Need", doi="10.5555/attention")
    fetch = make_fetch({"works/10.5555/attention": ATTENTION_PAPER})
    result = verify_reference(ref, fetch=fetch, http_head=make_head({}))
    import json
    json.dumps(result.to_dict())  # must not raise
