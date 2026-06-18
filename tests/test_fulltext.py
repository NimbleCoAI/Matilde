"""Tests for the open-access full-text locator (engine/fulltext.py).

Like the citations tests, all network I/O is injected — a fake ``fetch`` maps
request URLs to canned JSON, so the suite is deterministic and offline. The
locator resolves the best *legal* open-access location for a DOI via OpenAlex
(no key) + Unpaywall (needs a contact email) + an arXiv synthesis fallback. It
never returns a paywalled/pirated source — closed access returns is_oa=False.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from matilde_plugin.engine.fulltext import (  # noqa: E402
    FullTextResult,
    find_open_access,
)


# ---------------------------------------------------------------------------
# Canned provider responses
# ---------------------------------------------------------------------------

# OpenAlex work that is green-OA with a repository PDF.
OPENALEX_OA = {
    "doi": "https://doi.org/10.1234/oa-paper",
    "open_access": {"is_oa": True, "oa_status": "green",
                    "oa_url": "https://repo.example.org/oa-paper.pdf"},
    "best_oa_location": {
        "pdf_url": "https://repo.example.org/oa-paper.pdf",
        "landing_page_url": "https://repo.example.org/oa-paper",
        "license": "cc-by",
        "version": "publishedVersion",
        "source": {"type": "repository"},
    },
}

# OpenAlex work with NO open-access location (paywalled).
OPENALEX_CLOSED = {
    "doi": "https://doi.org/10.1234/closed-paper",
    "open_access": {"is_oa": False, "oa_status": "closed", "oa_url": None},
    "best_oa_location": None,
}

# Unpaywall says a paper OpenAlex thinks is closed actually has a gold PDF.
UNPAYWALL_OA = {
    "doi": "10.1234/closed-paper",
    "is_oa": True,
    "oa_status": "gold",
    "best_oa_location": {
        "url": "https://publisher.example.com/closed-paper",
        "url_for_pdf": "https://publisher.example.com/closed-paper.pdf",
        "license": "cc-by",
        "version": "publishedVersion",
        "host_type": "publisher",
    },
}


def make_fetch(routes: dict):
    """Return a fake fetch that maps a substring -> canned JSON (LookupError if
    no route matches, mirroring default_fetch's 404 behavior)."""
    calls = []

    def _fetch(url, timeout=20.0):
        calls.append(url)
        for needle, payload in routes.items():
            if needle in url:
                return payload
        raise LookupError(url)

    _fetch.calls = calls
    return _fetch


# ---------------------------------------------------------------------------
# OpenAlex (primary, no email needed)
# ---------------------------------------------------------------------------

def test_openalex_oa_with_pdf_is_resolved():
    fetch = make_fetch({"api.openalex.org": OPENALEX_OA})
    res = find_open_access("10.1234/oa-paper", fetch=fetch)
    assert isinstance(res, FullTextResult)
    assert res.is_oa is True
    assert res.pdf_url == "https://repo.example.org/oa-paper.pdf"
    assert res.best_url == "https://repo.example.org/oa-paper.pdf"
    assert res.oa_status == "green"
    assert res.source == "openalex"
    assert res.license == "cc-by"


def test_oa_without_direct_pdf_does_not_mislabel_landing_as_pdf():
    # OA work whose best_oa_location has NO pdf_url — only an oa_url landing page.
    # pdf_url must stay empty (don't claim a landing page is a PDF); best_url
    # falls back to the landing page so the agent still gets somewhere legal.
    work = {
        "doi": "https://doi.org/10.7554/elife.x",
        "open_access": {"is_oa": True, "oa_status": "gold",
                        "oa_url": "https://elifesciences.org/articles/x"},
        "best_oa_location": {
            "pdf_url": None,
            "landing_page_url": "https://elifesciences.org/articles/x",
            "license": "cc-by", "version": "publishedVersion",
            "source": {"type": "publisher"},
        },
    }
    fetch = make_fetch({"api.openalex.org": work})
    res = find_open_access("10.7554/elife.x", fetch=fetch)
    assert res.is_oa is True
    assert res.pdf_url == ""
    assert res.landing_url == "https://elifesciences.org/articles/x"
    assert res.best_url == "https://elifesciences.org/articles/x"


def test_closed_access_returns_not_oa():
    fetch = make_fetch({"api.openalex.org": OPENALEX_CLOSED})
    res = find_open_access("10.1234/closed-paper", fetch=fetch)
    assert res.is_oa is False
    assert res.best_url == ""
    assert res.pdf_url == ""
    assert res.oa_status == "closed"
    assert res.candidates == []


# ---------------------------------------------------------------------------
# Unpaywall fallback (needs email)
# ---------------------------------------------------------------------------

def test_unpaywall_fills_gap_when_openalex_closed():
    fetch = make_fetch({
        "api.openalex.org": OPENALEX_CLOSED,
        "api.unpaywall.org": UNPAYWALL_OA,
    })
    res = find_open_access("10.1234/closed-paper", fetch=fetch,
                           email="researcher@example.com")
    assert res.is_oa is True
    assert res.pdf_url == "https://publisher.example.com/closed-paper.pdf"
    assert res.source == "unpaywall"
    assert res.oa_status == "gold"


def test_unpaywall_skipped_without_email():
    # No email => Unpaywall must not be queried (its API requires one).
    fetch = make_fetch({
        "api.openalex.org": OPENALEX_CLOSED,
        "api.unpaywall.org": UNPAYWALL_OA,
    })
    res = find_open_access("10.1234/closed-paper", fetch=fetch, email=None)
    assert res.is_oa is False
    assert not any("unpaywall" in u for u in fetch.calls)


# ---------------------------------------------------------------------------
# arXiv synthesis fallback
# ---------------------------------------------------------------------------

def test_arxiv_doi_synthesizes_pdf_url_when_providers_miss():
    # OpenAlex 404s on this DOI; the arXiv DOI shape still yields a legal PDF.
    fetch = make_fetch({})  # everything LookupErrors
    res = find_open_access("10.48550/arXiv.1706.03762", fetch=fetch)
    assert res.is_oa is True
    assert res.pdf_url == "https://arxiv.org/pdf/1706.03762"
    assert res.source == "arxiv"


# ---------------------------------------------------------------------------
# External resolver hook (provider-neutral; opt-in via resolver_url)
# ---------------------------------------------------------------------------

# A configured external resolver answers with a full-text URL for a paywalled
# work. Its OA status is unknown/none — the result must NOT claim open access.
EXTERNAL_HIT = {"pdf_url": "https://resolver.example.net/files/closed-paper.pdf"}


def test_external_resolver_used_when_oa_misses():
    fetch = make_fetch({
        "api.openalex.org": OPENALEX_CLOSED,
        "resolver.example.net": EXTERNAL_HIT,
    })
    res = find_open_access("10.1234/closed-paper", fetch=fetch,
                           resolver_url="https://resolver.example.net")
    assert res.best_url == "https://resolver.example.net/files/closed-paper.pdf"
    assert res.pdf_url == "https://resolver.example.net/files/closed-paper.pdf"
    assert res.source == "external-resolver"
    # Honesty: an external resolver is NOT open access — don't mislabel it.
    assert res.is_oa is False


def test_external_resolver_skipped_when_unset():
    fetch = make_fetch({
        "api.openalex.org": OPENALEX_CLOSED,
        "resolver.example.net": EXTERNAL_HIT,
    })
    res = find_open_access("10.1234/closed-paper", fetch=fetch, resolver_url=None)
    assert res.best_url == ""
    assert not any("resolver.example.net" in u for u in fetch.calls)


def test_external_resolver_not_consulted_when_legal_oa_exists():
    # The legal OA copy wins; the external resolver (maybe Sci-Hub) is never hit.
    fetch = make_fetch({
        "api.openalex.org": OPENALEX_OA,
        "resolver.example.net": EXTERNAL_HIT,
    })
    res = find_open_access("10.1234/oa-paper", fetch=fetch,
                           resolver_url="https://resolver.example.net")
    assert res.source == "openalex"
    assert res.is_oa is True
    assert not any("resolver.example.net" in u for u in fetch.calls)


def test_external_resolver_miss_falls_through_to_closed():
    fetch = make_fetch({
        "api.openalex.org": OPENALEX_CLOSED,
        "resolver.example.net": {"pdf_url": None},
    })
    res = find_open_access("10.1234/closed-paper", fetch=fetch,
                           resolver_url="https://resolver.example.net")
    assert res.best_url == ""
    assert res.is_oa is False


# ---------------------------------------------------------------------------
# DOI normalization
# ---------------------------------------------------------------------------

def test_doi_url_is_normalized_before_query():
    fetch = make_fetch({"api.openalex.org": OPENALEX_OA})
    find_open_access("https://doi.org/10.1234/oa-paper", fetch=fetch)
    assert any("doi:10.1234/oa-paper" in u for u in fetch.calls)


def test_to_dict_is_json_serializable():
    fetch = make_fetch({"api.openalex.org": OPENALEX_OA})
    res = find_open_access("10.1234/oa-paper", fetch=fetch)
    d = res.to_dict()
    json.dumps(d)  # must not raise
    assert d["is_oa"] is True
    assert d["pdf_url"] == "https://repo.example.org/oa-paper.pdf"
