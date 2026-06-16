"""Matilde verifiable-citations engine — axes 1-3.

A citation is checked along four independent axes:

  1. existence       — does the cited work actually exist? (Crossref by DOI, else
                       title search)
  2. metadata-match  — do title / authors / year agree with the authoritative record?
  3. retraction      — has the work been retracted? (Crossref ``update-to`` /
                       ``relation.is-retracted-by``; Crossref owns the Retraction
                       Watch dataset)
  3b. url-liveness   — if a URL is given, does it resolve? (HTTP HEAD, with an
                       Internet Archive Wayback fallback)

The fourth axis — *claim-support grounding* (does the cited passage actually
substantiate the sentence that cites it?) — is intentionally **not** in v1. It is
the probabilistic frontier (GROBID + SemanticCite/SciFact) and lands in v2.

Design: all network I/O is injected. ``verify_*`` functions take a ``fetch``
callable ``(url) -> parsed JSON dict`` (raising ``LookupError`` on 404) and an
``http_head`` callable ``(url) -> (status_int_or_None, final_url)``. Production
defaults using the stdlib (``default_fetch`` / ``default_head``) are provided, but
every code path is unit-testable without a network by passing fakes.

Honest naming note: this is *verifiable*, not *provably correct*. Axes 1-3 are
near-deterministic; the composite is a confidence score, not a proof.
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable, Optional

# Title-match threshold (RefChecker / mcp-refchecker use ~0.85 fuzzy on titles).
TITLE_MATCH_THRESHOLD = 0.85
# Below this, a candidate title is considered a different paper entirely.
TITLE_DISTINCT_THRESHOLD = 0.60

CROSSREF_BASE = "https://api.crossref.org"
OPENALEX_BASE = "https://api.openalex.org"
DATACITE_BASE = "https://api.datacite.org"
WAYBACK_API = "https://archive.org/wayback/available"

FetchFn = Callable[..., dict]
HeadFn = Callable[..., tuple]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Reference:
    """A citation to verify. Populate whatever fields you have; more is better."""

    raw: str = ""                       # original citation string (optional)
    title: str = ""
    authors: list = field(default_factory=list)  # surnames or "First Last" strings
    year: Optional[int] = None
    doi: str = ""
    venue: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        # Normalize a DOI URL / "doi:" prefix down to the bare DOI.
        self.doi = _normalize_doi(self.doi)


@dataclass
class AxisResult:
    """The outcome of one verification axis.

    status: one of "pass" | "warn" | "fail" | "unknown".
      - For most axes, "pass" is good. For *retraction*, "pass" means NOT retracted
        and "fail" means IS retracted (a failure of the citation, not the check).
    confidence: 0..1 — how sure we are of this status.
    detail: human-readable one-liner.
    evidence: structured supporting data (the source record, matched fields, …).
    """

    status: str
    confidence: float = 0.0
    detail: str = ""
    evidence: dict = field(default_factory=dict)


@dataclass
class VerificationResult:
    reference: Reference
    existence: AxisResult
    metadata_match: AxisResult
    retraction: AxisResult
    url_liveness: AxisResult
    score: float = 0.0          # composite verifiability [0..1]
    verdict: str = "unverifiable"  # verified | warnings | retracted | not_found | unverifiable

    def to_dict(self) -> dict:
        """A JSON-safe dict (for tool envelopes / persistence)."""
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# String primitives
# ---------------------------------------------------------------------------

def _normalize_doi(doi: str) -> str:
    if not doi:
        return ""
    doi = doi.strip()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi, flags=re.I)
    doi = re.sub(r"^doi:\s*", "", doi, flags=re.I)
    return doi.strip()


def _norm_title(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def title_similarity(a: str, b: str) -> float:
    """Return a 0..1 similarity for two titles (case/punctuation-insensitive)."""
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _surname(name: str) -> str:
    """Best-effort surname extraction from 'First Last' or 'Last'."""
    name = name.strip()
    if not name:
        return ""
    # Handle "Last, First"
    if "," in name:
        return _norm_title(name.split(",")[0]).strip()
    parts = _norm_title(name).split()
    return parts[-1] if parts else ""


def author_overlap(ref_authors: list, record_authors: list) -> float:
    """Fraction of *ref_authors* whose surname appears among *record_authors*.

    ``record_authors`` may be plain strings or Crossref author dicts
    (``{"family": ..., "given": ...}``). Returns 0.0 if ``ref_authors`` is empty
    (nothing to corroborate).
    """
    ref_surnames = [s for s in (_surname(a) for a in ref_authors) if s]
    if not ref_surnames:
        return 0.0

    rec_surnames = set()
    for a in record_authors:
        if isinstance(a, dict):
            fam = a.get("family") or a.get("name") or ""
            rec_surnames.add(_surname(fam))
        else:
            rec_surnames.add(_surname(str(a)))
    rec_surnames.discard("")

    matched = sum(1 for s in ref_surnames if s in rec_surnames)
    return matched / len(ref_surnames)


def _record_title(message: dict) -> str:
    t = message.get("title") or []
    return t[0] if isinstance(t, list) and t else (t if isinstance(t, str) else "")


def _openalex_to_record(work: dict) -> dict:
    """Normalize an OpenAlex ``work`` into the Crossref-ish dict shape the rest
    of the engine consumes (so ``_record_title`` / ``_record_year`` /
    ``author_overlap`` / ``_retraction_signal`` all work unchanged).

    OpenAlex aggregates Crossref, DataCite (arXiv, Zenodo, …), PubMed and more,
    so it's the right fallback when a DOI isn't in Crossref. It also carries an
    authoritative ``is_retracted`` flag.
    """
    authors = []
    for a in work.get("authorships", []) or []:
        name = ((a or {}).get("author") or {}).get("display_name") or ""
        if name:
            authors.append({"family": name})
    year = work.get("publication_year")
    doi = _normalize_doi(work.get("doi") or "")
    return {
        "_source": "openalex",
        "DOI": doi,
        "title": [work.get("display_name") or ""],
        "author": authors,
        "published": {"date-parts": [[year]]} if year else {},
        "is_retracted": bool(work.get("is_retracted")),
        "openalex_id": work.get("id"),
    }


def _datacite_to_record(data: dict) -> dict:
    """Normalize a DataCite ``/dois/{doi}`` response into the common record shape.

    DataCite is the registration agency for arXiv (10.48550/*), Zenodo, figshare,
    Dryad and most data/preprint DOIs — the authoritative existence check when a
    DOI isn't in Crossref or OpenAlex.
    """
    attrs = (data.get("data") or {}).get("attributes") or data.get("attributes") or {}
    titles = attrs.get("titles") or []
    title = titles[0].get("title") if titles else ""
    authors = []
    for cr in attrs.get("creators", []) or []:
        fam = cr.get("familyName") or cr.get("name") or ""
        if fam:
            authors.append({"family": fam})
    year = attrs.get("publicationYear")
    return {
        "_source": "datacite",
        "DOI": _normalize_doi(attrs.get("doi") or ""),
        "title": [title or ""],
        "author": authors,
        "published": {"date-parts": [[year]]} if year else {},
    }


def _record_year(message: dict) -> Optional[int]:
    for key in ("published", "published-print", "published-online", "issued"):
        node = message.get(key) or {}
        parts = node.get("date-parts") or []
        if parts and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                continue
    return None


# ---------------------------------------------------------------------------
# Axis 1: existence
# ---------------------------------------------------------------------------

def verify_existence(ref: Reference, fetch: FetchFn) -> AxisResult:
    """Does the cited work exist? Prefer DOI lookup; fall back to title search."""
    if ref.doi:
        url = f"{CROSSREF_BASE}/works/{urllib.parse.quote(ref.doi)}"
        try:
            data = fetch(url)
            message = data.get("message", data)
            return AxisResult(
                status="pass", confidence=0.95,
                detail=f"DOI {ref.doi} resolves to a Crossref record.",
                evidence={"record": message, "matched_by": "doi", "source": "crossref"},
            )
        except LookupError:
            pass  # not in Crossref — fall back to OpenAlex before crying fabrication

        oa = _openalex_by_doi(ref.doi, fetch)
        if oa is not None:
            return AxisResult(
                status="pass", confidence=0.9,
                detail=f"DOI {ref.doi} resolves via OpenAlex (not in Crossref).",
                evidence={"record": oa, "matched_by": "doi", "source": "openalex"},
            )

        dc = _datacite_by_doi(ref.doi, fetch)
        if dc is not None:
            return AxisResult(
                status="pass", confidence=0.9,
                detail=f"DOI {ref.doi} resolves via DataCite "
                       f"(e.g. an arXiv/Zenodo/figshare DOI).",
                evidence={"record": dc, "matched_by": "doi", "source": "datacite"},
            )
        return AxisResult(
            status="fail", confidence=0.9,
            detail=f"DOI {ref.doi} does not resolve in Crossref, OpenAlex, or "
                   f"DataCite — likely fabricated.",
            evidence={"doi": ref.doi},
        )

    if ref.title:
        url = f"{CROSSREF_BASE}/works?query.bibliographic={urllib.parse.quote(ref.title)}&rows=5"
        try:
            data = fetch(url)
        except LookupError:
            return AxisResult(status="unknown", confidence=0.3,
                              detail="Crossref title search returned nothing.")
        items = (data.get("message", {}) or {}).get("items", []) or []
        best, best_sim = None, 0.0
        for item in items:
            sim = title_similarity(ref.title, _record_title(item))
            if sim > best_sim:
                best, best_sim = item, sim
        if best is not None and best_sim >= TITLE_MATCH_THRESHOLD:
            return AxisResult(
                status="pass", confidence=best_sim,
                detail=f"Title matched a Crossref record (similarity {best_sim:.2f}).",
                evidence={"record": best, "matched_by": "title", "similarity": best_sim},
            )
        return AxisResult(
            status="unknown", confidence=0.4,
            detail=f"No Crossref title match above {TITLE_MATCH_THRESHOLD:.2f} "
                   f"(best {best_sim:.2f}).",
            evidence={"best_similarity": best_sim},
        )

    return AxisResult(status="unknown", confidence=0.0,
                      detail="No DOI or title supplied — cannot check existence.")


def _openalex_by_doi(doi: str, fetch: FetchFn) -> Optional[dict]:
    """Return a normalized record for *doi* from OpenAlex, or None if absent."""
    doi = _normalize_doi(doi)
    if not doi:
        return None
    url = f"{OPENALEX_BASE}/works/doi:{urllib.parse.quote(doi)}"
    try:
        work = fetch(url)
    except LookupError:
        return None
    if not work or work.get("id") is None and not work.get("display_name"):
        return None
    return _openalex_to_record(work)


def _datacite_by_doi(doi: str, fetch: FetchFn) -> Optional[dict]:
    """Return a normalized record for *doi* from DataCite, or None if absent."""
    doi = _normalize_doi(doi)
    if not doi:
        return None
    url = f"{DATACITE_BASE}/dois/{urllib.parse.quote(doi)}"
    try:
        data = fetch(url)
    except LookupError:
        return None
    if not data or not (data.get("data") or data.get("attributes")):
        return None
    return _datacite_to_record(data)


# ---------------------------------------------------------------------------
# Axis 2: metadata match
# ---------------------------------------------------------------------------

def check_metadata_match(ref: Reference, record: dict) -> AxisResult:
    """Do the citation's title/authors/year agree with the authoritative record?"""
    if not record:
        return AxisResult(status="unknown", detail="No record to compare against.")

    rec_title = _record_title(record)
    sim = title_similarity(ref.title, rec_title) if ref.title else 1.0
    if ref.title and sim < TITLE_DISTINCT_THRESHOLD:
        return AxisResult(
            status="fail", confidence=1.0 - sim,
            detail=f"Title disagrees with the record (similarity {sim:.2f}): "
                   f"cited '{ref.title}' vs record '{rec_title}'.",
            evidence={"title_similarity": sim, "record_title": rec_title},
        )

    warnings = []
    evidence: dict = {"title_similarity": sim, "record_title": rec_title}

    rec_year = _record_year(record)
    if ref.year and rec_year and ref.year != rec_year:
        warnings.append(f"year mismatch (cited {ref.year}, record {rec_year})")
        evidence["record_year"] = rec_year

    overlap = author_overlap(ref.authors, record.get("author", []))
    evidence["author_overlap"] = overlap
    if ref.authors and overlap < 0.5:
        warnings.append(f"author overlap low ({overlap:.0%})")

    if warnings:
        return AxisResult(status="warn", confidence=0.6,
                          detail="; ".join(warnings) + ".", evidence=evidence)
    return AxisResult(status="pass", confidence=max(sim, 0.8),
                      detail="Title, authors, and year agree with the record.",
                      evidence=evidence)


# ---------------------------------------------------------------------------
# Axis 3: retraction
# ---------------------------------------------------------------------------

def _retraction_signal(message: dict) -> Optional[str]:
    """Return a human label if *message* shows the work is retracted, else None.

    Crossref exposes retraction on the affected work in a few shapes. Validated
    against the real API (e.g. the retracted Wakefield 1998 Lancet paper), the
    *primary* signal is the ``updated-by`` array — entries whose ``type`` is
    "retraction" (alongside any "correction" entries), typically carrying
    ``source: retraction-watch``. Crossref ingests the Retraction Watch dataset
    daily. Older/other records may instead use ``update-to`` or a
    ``relation.is-retracted-by`` link, so we check all three.
    """
    # OpenAlex carries an authoritative boolean flag (normalized into our record).
    if message.get("is_retracted"):
        return "retraction (OpenAlex is_retracted)"
    for upd in message.get("updated-by", []) or []:
        if isinstance(upd, dict) and "retract" in str(upd.get("type", "")).lower():
            return upd.get("label") or "retraction"
    for upd in message.get("update-to", []) or []:
        if isinstance(upd, dict) and "retract" in str(upd.get("type", "")).lower():
            return upd.get("label") or "retraction"
    relation = message.get("relation", {}) or {}
    for key in relation:
        if "retract" in key.lower() and relation[key]:
            return key
    return None


def check_retraction(doi: str, fetch: FetchFn) -> AxisResult:
    """Has the work with *doi* been retracted? ('fail' == retracted.)"""
    doi = _normalize_doi(doi)
    if not doi:
        return AxisResult(status="unknown", detail="No DOI — cannot check retraction.")
    url = f"{CROSSREF_BASE}/works/{urllib.parse.quote(doi)}"
    try:
        data = fetch(url)
    except LookupError:
        return AxisResult(status="unknown", confidence=0.3,
                          detail="DOI not found in Crossref; retraction status unknown.")
    message = data.get("message", data)
    label = _retraction_signal(message)
    if label:
        return AxisResult(status="fail", confidence=0.95,
                          detail=f"Work is RETRACTED ({label}).",
                          evidence={"signal": label})
    return AxisResult(status="pass", confidence=0.9,
                      detail="No retraction recorded in Crossref.")


# ---------------------------------------------------------------------------
# Axis 3b: URL liveness
# ---------------------------------------------------------------------------

def check_url_liveness(url: str, http_head: HeadFn,
                       fetch: Optional[FetchFn] = None) -> AxisResult:
    """Does *url* resolve? Dead URLs fall back to an Internet Archive check."""
    if not url:
        return AxisResult(status="unknown", detail="No URL supplied.")
    status, final = http_head(url)
    if status is not None and 200 <= status < 400:
        return AxisResult(status="pass", confidence=0.9,
                          detail=f"URL is live (HTTP {status}).",
                          evidence={"http_status": status, "final_url": final})

    # Dead or unreachable — check the Wayback Machine for an archived snapshot.
    archived = None
    if fetch is not None:
        try:
            data = fetch(f"{WAYBACK_API}?url={urllib.parse.quote(url)}")
            snap = (data.get("archived_snapshots", {}) or {}).get("closest", {})
            if snap.get("available"):
                archived = snap.get("url")
        except LookupError:
            archived = None

    if archived:
        return AxisResult(status="warn", confidence=0.6,
                          detail=f"URL is dead (HTTP {status}) but archived in the "
                                 f"Wayback Machine.",
                          evidence={"http_status": status, "wayback_url": archived})
    return AxisResult(status="fail", confidence=0.8,
                      detail=f"URL does not resolve (HTTP {status}) and is not archived.",
                      evidence={"http_status": status})


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _axis_weight(result: AxisResult, weights: dict) -> float:
    return weights.get(result.status, 0.0)


def verify_reference(ref: Reference, fetch: Optional[FetchFn] = None,
                     http_head: Optional[HeadFn] = None) -> VerificationResult:
    """Run all v1 axes and produce a composite verdict + score.

    Verdict precedence: a retraction dominates everything; a non-resolving DOI
    means ``not_found``; otherwise the score combines existence, metadata-match,
    and URL liveness.
    """
    fetch = fetch or default_fetch
    http_head = http_head or default_head

    existence = verify_existence(ref, fetch=fetch)
    record = existence.evidence.get("record") if existence.status == "pass" else None

    if record:
        metadata = check_metadata_match(ref, record)
    else:
        metadata = AxisResult(status="unknown", detail="No record to compare against.")

    # Reuse the already-fetched record for retraction when we have it.
    if record is not None:
        label = _retraction_signal(record)
        if label:
            retraction = AxisResult(status="fail", confidence=0.95,
                                    detail=f"Work is RETRACTED ({label}).",
                                    evidence={"signal": label})
        else:
            retraction = AxisResult(status="pass", confidence=0.9,
                                    detail="No retraction recorded in Crossref.")
    else:
        doi = ref.doi or ""
        retraction = check_retraction(doi, fetch=fetch) if doi else \
            AxisResult(status="unknown", detail="No DOI — cannot check retraction.")

    url_liveness = check_url_liveness(ref.url, http_head=http_head, fetch=fetch) \
        if ref.url else AxisResult(status="unknown", detail="No URL supplied.")

    # --- Verdict + score ---
    if retraction.status == "fail":
        verdict, score = "retracted", 0.1
    elif existence.status == "fail":
        verdict, score = "not_found", 0.1
    elif existence.status == "unknown":
        verdict, score = "unverifiable", 0.4
    else:
        ex = 0.5  # existence passed
        meta = _axis_weight(metadata, {"pass": 0.3, "warn": 0.18, "unknown": 0.15, "fail": 0.0})
        live = _axis_weight(url_liveness, {"pass": 0.2, "warn": 0.12, "unknown": 0.1, "fail": 0.0})
        score = round(ex + meta + live, 3)
        if metadata.status == "fail":
            verdict = "warnings"
        elif score >= 0.8:
            verdict = "verified"
        else:
            verdict = "warnings"

    return VerificationResult(
        reference=ref,
        existence=existence,
        metadata_match=metadata,
        retraction=retraction,
        url_liveness=url_liveness,
        score=score,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Production I/O defaults (stdlib only)
# ---------------------------------------------------------------------------

def _user_agent() -> str:
    contact = os.environ.get("MATILDE_CONTACT_EMAIL", "").strip()
    base = "Matilde-citation-verifier/0.1 (https://github.com/NimbleCoAI/Matilde)"
    return f"{base} mailto:{contact}" if contact else base


def default_fetch(url: str, timeout: float = 20.0) -> dict:
    """GET *url* and parse JSON. Raises ``LookupError`` on HTTP 404."""
    req = urllib.request.Request(url, headers={"User-Agent": _user_agent(),
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        if exc.code == 404:
            raise LookupError(url) from exc
        raise


def default_head(url: str, timeout: float = 15.0) -> tuple:
    """HEAD *url*; return ``(status, final_url)``. Falls back to GET if HEAD is
    rejected. Returns ``(None, url)`` if the host is unreachable."""
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method,
                                     headers={"User-Agent": _user_agent()})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return (resp.status, resp.geturl())
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            if method == "HEAD" and exc.code in (403, 405, 501):
                continue  # some servers reject HEAD; retry with GET
            return (exc.code, url)
        except Exception:
            return (None, url)
    return (None, url)
