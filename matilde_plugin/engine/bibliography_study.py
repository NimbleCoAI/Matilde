"""Bibliography-validation study — the first concrete pipeline.

Three steps, reusing the existing parsing + citations engine:

  1. ``parse_refs``  — parse a BibTeX blob into ``Reference`` objects.
  2. ``verify_each`` — verify each reference, recording one *finding* per ref.
  3. ``summarize``   — roll the findings up into a per-verdict tally.

This is deliberately lightweight (no heavy scientific deps) and exists to *prove
the framework*: it is the worked example for resumability. ``verify_each`` is
written to be safe to re-run from scratch — on resume it skips references that
already have a persisted finding — so when the verifier fails partway through, a
later ``resume`` continues from the unfinished reference without re-verifying the
ones that already passed. (The runner only skips done *steps*; mid-step
idempotency is the step's own responsibility — see ``pipeline`` docstring.)

The verifier is **injected**: ``verifier(ref) -> {claim, verdict, score,
evidence}``. Production passes :func:`default_verifier` (which wraps the real
citations engine); tests pass a fake that can force a failure on a chosen ref.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from .citations import Reference, verify_reference
from .parsing import parse_bibtex
from .pipeline import Step, StepContext, StepResult

VerifierFn = Callable[[Reference], dict]

# Map the citation engine's verdicts onto the finding vocabulary
# (supported | refuted | inconclusive) the study records.
_VERDICT_MAP = {
    "verified": "supported",
    "warnings": "inconclusive",
    "unverifiable": "inconclusive",
    "not_found": "refuted",
    "retracted": "refuted",
}


def _ref_key(ref: Reference) -> str:
    """A stable identifier for a reference (for resume de-duplication + claims)."""
    return ref.doi or ref.title or ref.raw[:80] or "(unidentified)"


def default_verifier(ref: Reference) -> dict:
    """Verify *ref* with the real citations engine (network). Injected in prod."""
    result = verify_reference(ref)
    verdict = _VERDICT_MAP.get(result.verdict, "inconclusive")
    return {
        "claim": f"reference is valid: {_ref_key(ref)}",
        "verdict": verdict,
        "score": result.score,
        "evidence": {
            "citation_verdict": result.verdict,
            "axes": {
                "existence": result.existence.status,
                "metadata_match": result.metadata_match.status,
                "retraction": result.retraction.status,
                "url_liveness": result.url_liveness.status,
            },
        },
    }


def _parse_refs_step(bibtex: str) -> Step:
    def fn(ctx: StepContext) -> StepResult:
        refs = parse_bibtex(bibtex)
        return StepResult(data={
            "count": len(refs),
            "refs": [r.raw or _ref_key(r) for r in refs],
        })
    return Step(name="parse_refs", fn=fn)


def _verify_each_step(bibtex: str, verifier: VerifierFn) -> Step:
    def fn(ctx: StepContext) -> StepResult:
        refs = parse_bibtex(bibtex)
        # Resume-safe: skip refs that already have a persisted finding.
        already = {f["evidence"].get("ref_key")
                   for f in ctx.store.get_findings(ctx.study_id)
                   if f["step_name"] == "verify_each"}
        for ref in refs:
            key = _ref_key(ref)
            if key in already:
                continue
            v = verifier(ref)  # may raise -> step fails, study resumable
            evidence = dict(v.get("evidence") or {})
            evidence["ref_key"] = key
            # Persist immediately so a later failure doesn't lose this ref.
            ctx.store.add_finding(
                ctx.study_id, "verify_each",
                claim=v.get("claim", f"reference: {key}"),
                verdict=v.get("verdict", "inconclusive"),
                score=v.get("score"),
                evidence=evidence)
        return StepResult(data={"verified": len(refs)})
    return Step(name="verify_each", fn=fn)


def _summarize_step() -> Step:
    def fn(ctx: StepContext) -> StepResult:
        findings = [f for f in ctx.store.get_findings(ctx.study_id)
                    if f["step_name"] == "verify_each"]
        counts: dict = {}
        for f in findings:
            counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1
        return StepResult(data={
            "total": len(findings),
            "supported": counts.get("supported", 0),
            "refuted": counts.get("refuted", 0),
            "inconclusive": counts.get("inconclusive", 0),
            "by_verdict": counts,
        })
    return Step(name="summarize", fn=fn)


def build_steps(bibtex: str, verifier: Optional[VerifierFn] = None) -> List[Step]:
    """Build the ``parse_refs -> verify_each -> summarize`` steps for *bibtex*.

    Pass *verifier* to inject the per-reference check (defaults to the real
    citations engine). The returned steps are fed to ``pipeline.run`` / ``resume``.
    """
    verifier = verifier or default_verifier
    return [
        _parse_refs_step(bibtex),
        _verify_each_step(bibtex, verifier),
        _summarize_step(),
    ]
