"""Base protocol, result dataclass, archival utility, and collector registry.

This module is the foundation every collector in your package builds on.
Copy this file to ``collectors/base.py`` (or keep it here and import from
``example_collectors.base``) — whichever layout matches your package structure.

Nothing here is domain-specific.  The only caller-visible change you should
make is to the fields of ``CollectionResult`` if your domain needs more
structured output than the defaults.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class CollectionResult:
    """The normalized output every collector must return.

    Fields
    ------
    raw_response : bytes
        The verbatim bytes returned by the external source (HTTP body, file
        contents, API JSON, etc.).  Used for archiving and audit.

    content_type : str
        MIME type or informal label describing ``raw_response``
        (e.g. ``"application/json"``, ``"text/html"``, ``"binary"``).

    candidate_entities : list[dict]
        Structured entities extracted from the response.  Schema is
        domain-defined — document it in your collector's docstring.
        Example keys: ``{"name": "...", "type": "...", "identifiers": {...}}``.

    candidate_items : list[dict]
        Domain-specific structured items (claims, findings, indicators, …)
        extracted from the response.  Rename the field to suit your domain
        (e.g. ``candidate_indicators``, ``candidate_findings``).

    metadata : dict
        Collector-specific provenance: query params, pagination cursors,
        response headers worth keeping, etc.
    """

    raw_response: bytes
    content_type: str
    candidate_entities: list[dict[str, Any]]
    candidate_items: list[dict[str, Any]]       # rename to match your domain
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Collector protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Collector(Protocol):
    """Structural protocol every collector must satisfy.

    Implement these two attributes and one method on your collector class.
    No base class required — duck typing only.

    Attributes
    ----------
    name : str
        Short machine-readable identifier, e.g. ``"my_api_v2"``.
        Used as a key in the registry and in audit logs.

    source_reliability : str
        A single-letter grade (A–F) or a human label (``"high"`` / ``"medium"``
        / ``"low"``) describing the overall reliability of this source.
        Feeds into ``engine.score_record``.
    """

    name: str
    source_reliability: str

    def collect(self, query: str, **params: Any) -> CollectionResult:
        """Run a collection query and return structured results.

        Args:
            query: The primary search term or identifier.  Domain-defined —
                   could be a name, a URL, an ID, a file path, etc.
            **params: Collector-specific keyword arguments (API keys,
                      pagination params, filters, …).  Document these in the
                      concrete collector's docstring.

        Returns:
            A populated ``CollectionResult``.

        Raises:
            CollectorError: (optional) Raise a domain-specific exception
                            rather than letting raw HTTP/IO errors bubble up.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Archival helper
# ---------------------------------------------------------------------------

def archive_raw(content: bytes, artifacts_dir: str) -> tuple[str, str]:
    """Content-address and store raw bytes.

    SHA-256 hashes *content* and writes it as ``{hash[:16]}.bin`` inside
    *artifacts_dir*.  The operation is idempotent: identical content always
    maps to the same path and is only written once.

    Args:
        content: Raw bytes to archive (usually ``CollectionResult.raw_response``).
        artifacts_dir: Directory in which to write the file (created if absent).

    Returns:
        A 2-tuple of ``(full_hex_hash, absolute_file_path)``.

    Example::

        hash_, path = archive_raw(result.raw_response, "engagements/acme/artifacts")
        record = DomainRecord(..., raw_hash=hash_)
    """
    os.makedirs(artifacts_dir, exist_ok=True)
    full_hash = hashlib.sha256(content).hexdigest()
    file_path = os.path.join(artifacts_dir, f"{full_hash[:16]}.bin")
    if not os.path.exists(file_path):
        with open(file_path, "wb") as fh:
            fh.write(content)
    return full_hash, file_path


# ---------------------------------------------------------------------------
# Collector registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type] = {}


def register_collector(name: str, cls: type) -> None:
    """Register *cls* under *name* in the global collector registry.

    Call this at module import time so the harness skill can enumerate
    available collectors without instantiating them.

    Example::

        register_collector("example", ExampleCollector)
    """
    _REGISTRY[name] = cls


def get_collector(name: str) -> type | None:
    """Return the collector class registered under *name*, or ``None``."""
    return _REGISTRY.get(name)


def list_collectors() -> list[str]:
    """Return a sorted list of all registered collector names."""
    return sorted(_REGISTRY.keys())
