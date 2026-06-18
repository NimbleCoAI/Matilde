"""Open-access full-text locator.

Given a DOI, resolve the best *legal* open-access location for the work — a
direct PDF where one exists, otherwise an OA landing page. Sources, in priority
order, are all free and unauthenticated (or email-gated, never key-gated):

  1. **OpenAlex** — ``open_access`` + ``best_oa_location`` (no email needed).
  2. **Unpaywall** — queried only when a contact email is supplied (its API
     requires ``?email=``). Often finds a publisher/repository OA copy OpenAlex
     hasn't indexed yet.
  3. **arXiv synthesis** — an arXiv-registered DOI (``10.48550/arXiv.<id>``)
     always has a legal PDF at ``arxiv.org/pdf/<id>``, even if the providers miss.

This locator only ever returns open-access sources. A paywalled work resolves to
``is_oa=False`` with no URL — it deliberately does **not** route around a
paywall. The point is to give a citation-verifier the *content* it can legally
read to ground a claim, not to bypass access controls.

Design mirrors ``citations``: all network I/O is injected via a ``fetch`` callable
``(url) -> parsed JSON dict`` (raising ``LookupError`` on 404), so every path is
unit-testable without a network. ``default_fetch`` is the stdlib production default.
"""
from __future__ import annotations

import dataclasses
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Optional

from .citations import OPENALEX_BASE, _normalize_doi, default_fetch

FetchFn = Callable[..., dict]

UNPAYWALL_BASE = "https://api.unpaywall.org/v2"
# arXiv-registered DOIs look like 10.48550/arXiv.1706.03762 (case-insensitive).
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.I)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FullTextResult:
    """The resolved best open-access location for a DOI (or a closed verdict)."""

    doi: str
    is_oa: bool = False
    oa_status: str = "unknown"   # gold | green | hybrid | bronze | closed | unknown
    best_url: str = ""           # best PDF if available, else best landing page
    pdf_url: str = ""
    landing_url: str = ""
    source: str = ""             # which provider produced the chosen location
    license: str = ""
    candidates: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Provider parsers (each returns a normalized loc dict, or None on miss)
# ---------------------------------------------------------------------------

def _try_openalex(doi: str, fetch: FetchFn) -> Optional[dict]:
    try:
        work = fetch(f"{OPENALEX_BASE}/works/doi:{doi}")
    except Exception:
        return None
    oa = work.get("open_access") or {}
    best = work.get("best_oa_location") or {}
    # Only ``pdf_url`` is a guaranteed direct PDF. ``oa_url`` is the "best OA URL"
    # but is often a landing page — treat it as a landing fallback, never a PDF.
    return {
        "is_oa": bool(oa.get("is_oa")),
        "oa_status": oa.get("oa_status") or "",
        "pdf_url": best.get("pdf_url") or "",
        "landing_url": best.get("landing_page_url") or oa.get("oa_url") or "",
        "license": best.get("license") or "",
        "version": best.get("version") or "",
        "host_type": (best.get("source") or {}).get("type") or "",
    }


def _try_unpaywall(doi: str, fetch: FetchFn, email: str) -> Optional[dict]:
    email_q = urllib.parse.quote(email)
    try:
        data = fetch(f"{UNPAYWALL_BASE}/{doi}?email={email_q}")
    except Exception:
        return None
    best = data.get("best_oa_location") or {}
    return {
        "is_oa": bool(data.get("is_oa")),
        "oa_status": data.get("oa_status") or "",
        "pdf_url": best.get("url_for_pdf") or "",
        "landing_url": best.get("url") or "",
        "license": best.get("license") or "",
        "version": best.get("version") or "",
        "host_type": best.get("host_type") or "",
    }


def _arxiv_pdf(doi: str) -> str:
    m = _ARXIV_DOI.match(doi)
    return f"https://arxiv.org/pdf/{m.group(1)}" if m else ""


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _from_loc(doi: str, loc: dict, source: str) -> FullTextResult:
    pdf = loc.get("pdf_url") or ""
    landing = loc.get("landing_url") or ""
    best = pdf or landing
    candidate = {
        "url": best, "pdf_url": pdf, "landing_url": landing,
        "license": loc.get("license") or "", "version": loc.get("version") or "",
        "host_type": loc.get("host_type") or "", "source": source,
    }
    return FullTextResult(
        doi=doi, is_oa=True, oa_status=loc.get("oa_status") or "unknown",
        best_url=best, pdf_url=pdf, landing_url=landing, source=source,
        license=loc.get("license") or "", candidates=[candidate],
    )


def find_open_access(doi: str, fetch: Optional[FetchFn] = None, *,
                     email: Optional[str] = None) -> FullTextResult:
    """Resolve the best legal open-access location for *doi*.

    Returns a :class:`FullTextResult`. ``is_oa=False`` means no open-access copy
    was found — the work is paywalled and this locator will not route around it.
    Pass *email* to enable the Unpaywall lookup (its API requires a contact
    address); without it, only OpenAlex + arXiv are consulted.
    """
    fetch = fetch or default_fetch
    doi = _normalize_doi(doi)
    result = FullTextResult(doi=doi)
    if not doi:
        return result

    # 1. OpenAlex (primary, no email needed)
    oa = _try_openalex(doi, fetch)
    if oa and oa["is_oa"] and (oa["pdf_url"] or oa["landing_url"]):
        return _from_loc(doi, oa, "openalex")
    if oa is not None:
        result.is_oa = oa["is_oa"]
        result.oa_status = oa["oa_status"] or "closed"

    # 2. Unpaywall (only with a contact email)
    if email:
        up = _try_unpaywall(doi, fetch, email)
        if up and up["is_oa"] and (up["pdf_url"] or up["landing_url"]):
            return _from_loc(doi, up, "unpaywall")

    # 3. arXiv synthesis — a registered arXiv DOI always has a legal PDF
    arx = _arxiv_pdf(doi)
    if arx:
        return _from_loc(doi, {"pdf_url": arx, "oa_status": "green",
                               "host_type": "repository"}, "arxiv")

    return result
