"""Matilde domain engine — verifiable academic citations.

The engine is the package's core: it verifies a citation along four independent
axes (existence, metadata-match, retraction, URL-liveness) and produces a
composite verifiability score and verdict. See :mod:`matilde_plugin.engine.citations`.

This is *verifiable*, not *provably correct* — axes 1-3 are near-deterministic;
claim-support grounding (does the cited passage substantiate the claim?) is the
probabilistic v2 axis and is not yet implemented.
"""
from __future__ import annotations

from .citations import (
    AxisResult,
    Reference,
    VerificationResult,
    check_retraction,
    check_metadata_match,
    check_url_liveness,
    default_fetch,
    default_head,
    title_similarity,
    verify_existence,
    verify_reference,
)

__all__ = [
    "AxisResult",
    "Reference",
    "VerificationResult",
    "check_retraction",
    "check_metadata_match",
    "check_url_liveness",
    "default_fetch",
    "default_head",
    "title_similarity",
    "verify_existence",
    "verify_reference",
]
