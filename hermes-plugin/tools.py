"""Matilde tools for Hermes — verifiable-citation checking.

These tools expose the ``engine.citations`` verifier to the agent. A citation is
checked along four axes (existence, metadata-match, retraction, URL-liveness) and
scored. This is *verifiable*, not *provably correct* — the score is a confidence,
not a proof. Claim-support grounding (does the cited passage back the claim?) is a
v2 axis and is not wired here.

No API key is required: Crossref, OpenAlex, and DataCite are all free and
unauthenticated. Set ``MATILDE_CONTACT_EMAIL`` to join the providers' polite
pools (recommended, not required).

Handlers are plain functions ``(args: dict, **kwargs) -> str`` returning a JSON
string built by ``_tool_result`` / ``_tool_error``. They never raise.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Path setup — make the package root importable (engine/ lives one level up).
# ---------------------------------------------------------------------------
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_ROOT = os.path.normpath(os.path.join(_PLUGIN_DIR, ".."))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)


# ---------------------------------------------------------------------------
# Shared envelope helpers
# ---------------------------------------------------------------------------

def _tool_result(data: Any = None, **kwargs: Any) -> str:
    if data is not None:
        payload = data if isinstance(data, dict) else {"result": data}
    else:
        payload = kwargs
    payload.setdefault("success", True)
    return json.dumps(payload, default=str)


def _tool_error(message: str, **extra: Any) -> str:
    return json.dumps({"error": message, "success": False, **extra}, default=str)


# ---------------------------------------------------------------------------
# Availability gate
# ---------------------------------------------------------------------------

def _check_available() -> bool:
    """Matilde's citation tools need no credentials — only that the engine imports.

    The provider APIs (Crossref/OpenAlex/DataCite) are free and unauthenticated,
    so the only real prerequisite is that the engine module loads.
    """
    try:
        import engine.citations  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Argument coercion
# ---------------------------------------------------------------------------

def _reference_from_args(d: dict) -> Any:
    from engine.citations import Reference
    authors = d.get("authors") or []
    if isinstance(authors, str):
        # accept "Vaswani; Shazeer" or "Vaswani, Shazeer"
        sep = ";" if ";" in authors else ","
        authors = [a.strip() for a in authors.split(sep) if a.strip()]
    year = d.get("year")
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    return Reference(
        raw=str(d.get("raw", "")),
        title=str(d.get("title", "")).strip(),
        authors=list(authors),
        year=year,
        doi=str(d.get("doi", "")).strip(),
        venue=str(d.get("venue", "")).strip(),
        url=str(d.get("url", "")).strip(),
    )


# ---------------------------------------------------------------------------
# Tool: verify a single citation
# ---------------------------------------------------------------------------

VERIFY_CITATION_SCHEMA = {
    "name": "matilde_verify_citation",
    "description": (
        "Verify a single academic citation along four axes — existence (does the "
        "work exist, via Crossref/OpenAlex/DataCite), metadata-match (do title/"
        "authors/year agree), retraction (Retraction Watch via Crossref/OpenAlex), "
        "and URL-liveness — and return a composite verifiability score (0-1) plus a "
        "verdict: verified | warnings | retracted | not_found | unverifiable. "
        "Provide as many fields as you have; a DOI gives the most reliable result. "
        "Use this before trusting any reference an LLM produced — hallucinated "
        "references are common."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "doi": {"type": "string", "description": "DOI (bare, or as a doi.org URL). Most reliable signal."},
            "title": {"type": "string", "description": "Paper title. Used for existence search when no DOI, and always for metadata-match."},
            "authors": {"type": "array", "items": {"type": "string"}, "description": "Author names or surnames (e.g. ['Vaswani', 'Shazeer'])."},
            "year": {"type": "integer", "description": "Publication year."},
            "venue": {"type": "string", "description": "Journal/conference (optional)."},
            "url": {"type": "string", "description": "A URL for the work, if cited. Checked for liveness with a Wayback fallback."},
        },
        "required": [],
    },
}


def _handle_verify_citation(args: dict, **kwargs: Any) -> str:
    if not (args.get("doi") or args.get("title")):
        return _tool_error("Provide at least a 'doi' or a 'title' to verify.")
    try:
        from engine.citations import verify_reference
        ref = _reference_from_args(args)
        result = verify_reference(ref)
        out = result.to_dict()
        return _tool_result(
            verdict=result.verdict,
            score=result.score,
            axes={
                "existence": result.existence.status,
                "metadata_match": result.metadata_match.status,
                "retraction": result.retraction.status,
                "url_liveness": result.url_liveness.status,
            },
            detail=out,
            message=f"Citation verdict: {result.verdict} (score {result.score}).",
        )
    except Exception as exc:  # never raise out of a handler
        return _tool_error(f"verify_citation failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool: verify a whole bibliography
# ---------------------------------------------------------------------------

VERIFY_BIBLIOGRAPHY_SCHEMA = {
    "name": "matilde_verify_bibliography",
    "description": (
        "Verify a list of citations at once and return per-reference verdicts plus "
        "a summary (counts by verdict, and the indices of any not_found or retracted "
        "references — the ones that most need attention). Use this to audit a "
        "reference list or bibliography in bulk."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "references": {
                "type": "array",
                "description": "List of citation objects, each with any of: doi, title, authors, year, venue, url.",
                "items": {
                    "type": "object",
                    "properties": {
                        "doi": {"type": "string"},
                        "title": {"type": "string"},
                        "authors": {"type": "array", "items": {"type": "string"}},
                        "year": {"type": "integer"},
                        "venue": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            },
        },
        "required": ["references"],
    },
}


def _handle_verify_bibliography(args: dict, **kwargs: Any) -> str:
    refs = args.get("references")
    if not isinstance(refs, list) or not refs:
        return _tool_error("'references' must be a non-empty list of citation objects.")
    try:
        from engine.citations import verify_reference
        results, summary = [], {}
        flagged = []
        for i, item in enumerate(refs):
            if not isinstance(item, dict):
                results.append({"index": i, "error": "not an object"})
                continue
            ref = _reference_from_args(item)
            r = verify_reference(ref)
            summary[r.verdict] = summary.get(r.verdict, 0) + 1
            if r.verdict in ("not_found", "retracted"):
                flagged.append({"index": i, "verdict": r.verdict,
                                "title": ref.title or ref.doi or ref.raw})
            results.append({
                "index": i, "verdict": r.verdict, "score": r.score,
                "title": ref.title or ref.doi, "detail": r.to_dict(),
            })
        return _tool_result(
            count=len(refs),
            summary=summary,
            needs_attention=flagged,
            results=results,
            message=(f"Verified {len(refs)} references: " +
                     ", ".join(f"{k}={v}" for k, v in sorted(summary.items())) +
                     (f". {len(flagged)} need attention." if flagged else ".")),
        )
    except Exception as exc:
        return _tool_error(f"verify_bibliography failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool: quick retraction check
# ---------------------------------------------------------------------------

CHECK_RETRACTION_SCHEMA = {
    "name": "matilde_check_retraction",
    "description": (
        "Quickly check whether a work (by DOI) has been retracted, using Crossref's "
        "Retraction Watch data. Returns status 'pass' (not retracted), 'fail' "
        "(RETRACTED), or 'unknown' (DOI not found / no DOI). Faster than a full "
        "verification when you only care about retraction status."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "doi": {"type": "string", "description": "DOI to check (bare or doi.org URL)."},
        },
        "required": ["doi"],
    },
}


def _handle_check_retraction(args: dict, **kwargs: Any) -> str:
    doi = str(args.get("doi", "")).strip()
    if not doi:
        return _tool_error("'doi' is required.")
    try:
        from engine.citations import check_retraction, default_fetch
        res = check_retraction(doi, fetch=default_fetch)
        return _tool_result(
            doi=doi,
            status=res.status,
            retracted=(res.status == "fail"),
            detail=res.detail,
            evidence=res.evidence,
            message=res.detail,
        )
    except Exception as exc:
        return _tool_error(f"check_retraction failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool: OpenNeuro dataset metadata
# ---------------------------------------------------------------------------

OPENNEURO_INFO_SCHEMA = {
    "name": "matilde_openneuro_dataset_info",
    "description": (
        "Get metadata for an OpenNeuro neuroimaging dataset by accession ID "
        "(e.g. 'ds000246'): human title, authors, imaging modalities (meg/mri/"
        "eeg/ieeg/ecog), subjects, tasks, total size, and latest snapshot tag. "
        "OpenNeuro hosts public BIDS-formatted brain-imaging datasets."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "description": "OpenNeuro accession ID, e.g. 'ds000246'."},
        },
        "required": ["dataset_id"],
    },
}


def _handle_openneuro_dataset_info(args: dict, **kwargs: Any) -> str:
    dsid = str(args.get("dataset_id", "")).strip()
    if not dsid:
        return _tool_error("'dataset_id' is required (e.g. 'ds000246').")
    try:
        from engine.openneuro import get_dataset, OpenNeuroError
        try:
            ds = get_dataset(dsid)
        except OpenNeuroError as exc:
            return _tool_error(str(exc), dataset_id=dsid)
        payload = ds.to_dict()
        payload["message"] = (f"{ds.id}: '{ds.name}' — modalities {ds.modalities}, "
                              f"{len(ds.subjects)} subject(s), {ds.size} bytes "
                              f"(snapshot {ds.latest_tag}).")
        return _tool_result(payload)
    except Exception as exc:
        return _tool_error(f"openneuro_dataset_info failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool: OpenNeuro dataset listing
# ---------------------------------------------------------------------------

OPENNEURO_SEARCH_SCHEMA = {
    "name": "matilde_openneuro_search",
    "description": (
        "List OpenNeuro dataset accession IDs (most recent first) to discover "
        "datasets. This lists rather than full-text-searches; call "
        "matilde_openneuro_dataset_info on candidates to inspect modalities/tasks "
        "and filter. Use to find brain-imaging datasets to analyze or replicate."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "description": "How many dataset IDs to return (default 20)."},
        },
        "required": [],
    },
}


def _handle_openneuro_search(args: dict, **kwargs: Any) -> str:
    try:
        from engine.openneuro import list_datasets
        limit = args.get("limit") or 20
        try:
            limit = max(1, min(int(limit), 100))
        except (TypeError, ValueError):
            limit = 20
        ids = list_datasets(limit=limit)
        return _tool_result(count=len(ids), dataset_ids=ids,
                            message=f"Listed {len(ids)} OpenNeuro dataset(s).")
    except Exception as exc:
        return _tool_error(f"openneuro_search failed: {type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool: OpenNeuro file listing
# ---------------------------------------------------------------------------

OPENNEURO_FILES_SCHEMA = {
    "name": "matilde_openneuro_list_files",
    "description": (
        "List the files in an OpenNeuro dataset's latest snapshot — filename, size, "
        "and a direct download URL for each. Use to inspect a dataset's structure "
        "(BIDS layout) or to get a URL for a specific file before downloading."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "description": "OpenNeuro accession ID, e.g. 'ds000246'."},
            "tag": {"type": "string", "description": "Snapshot tag (optional; defaults to the latest)."},
        },
        "required": ["dataset_id"],
    },
}


def _handle_openneuro_list_files(args: dict, **kwargs: Any) -> str:
    dsid = str(args.get("dataset_id", "")).strip()
    if not dsid:
        return _tool_error("'dataset_id' is required (e.g. 'ds000246').")
    try:
        from engine.openneuro import list_files, OpenNeuroError
        tag = str(args.get("tag", "")).strip() or None
        try:
            files = list_files(dsid, tag=tag)
        except OpenNeuroError as exc:
            return _tool_error(str(exc), dataset_id=dsid)
        return _tool_result(
            dataset_id=dsid, count=len(files), files=files,
            message=f"{dsid} has {len(files)} file(s) in its snapshot.",
        )
    except Exception as exc:
        return _tool_error(f"openneuro_list_files failed: {type(exc).__name__}: {exc}")
