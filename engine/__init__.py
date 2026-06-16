"""Public API for the {{PACKAGE_NAME}} domain engine.

This module is the optional "engine" layer — structured persistence and scoring
logic that sits between raw collector output and the Hermes skill.

Replace the example below with your domain's concepts, or delete ``engine/``
entirely if your use case doesn't need a local record store (e.g. you're
forwarding straight to an external system).

Typical contents when you do keep this layer:
  - models.py       — dataclasses / SQLite schema for your domain records
  - db.py           — thin SQLite wrapper (insert/query/update helpers)
  - scorer.py       — confidence / relevance scoring for aggregated records
  - audit.py        — append-only audit log (who ran what, when, with what result)
  - resolver.py     — entity dedup / merge logic (optional, domain-specific)

None of those sub-modules are provided here — they are domain-specific.
The only thing wired in this __init__ is a single generic function so the
package is importable and the pattern is clear.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Example record type — replace with your domain model
# ---------------------------------------------------------------------------

@dataclass
class DomainRecord:
    """A generic structured record produced by a collector run.

    Replace the fields below with whatever your domain needs — a threat
    indicator, a research finding, a patient observation, a legal filing, etc.

    ``record_id`` is set by ``RecordStore.add`` and should not be supplied by
    the caller.
    """

    # Caller-supplied fields — fill these in for your domain.
    subject: str               # The entity this record is about
    source_name: str           # Human-readable name of the data source
    source_reliability: str    # E.g. "A"–"F" or "high"/"medium"/"low"
    raw_hash: str              # SHA-256 hex of the archived raw bytes (from archive_raw)
    payload: dict[str, Any] = field(default_factory=dict)  # Domain-specific structured data

    # Set automatically by the store — do not supply.
    record_id: str = ""
    created_at: float = field(default_factory=time.time)
    score: float = 0.0         # Populated by score_record(); 0.0 until scored


# ---------------------------------------------------------------------------
# Example store — replace with your db.py / external sink
# ---------------------------------------------------------------------------

class RecordStore:
    """A minimal in-memory (or JSON-file-backed) record store.

    This is a scaffold — replace it with a real SQLite wrapper, a REST call,
    or whatever persistence layer makes sense for your domain.

    If you back it with a JSON file, be careful: the file is not encrypted.
    Sensitive operational data belongs in ``engagements/`` (gitignored) or
    an external store, not in version-controlled files.
    """

    def __init__(self, store_path: str | None = None) -> None:
        """Create or load a store.

        Args:
            store_path: Optional path to a JSON file.  If ``None``, the store
                        lives in memory only and is not persisted.
        """
        self._path = store_path
        self._records: dict[str, DomainRecord] = {}
        if store_path and os.path.exists(store_path):
            self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, record: DomainRecord) -> DomainRecord:
        """Assign a record_id, store the record, and return it.

        Idempotent on ``raw_hash``: if a record with the same hash already
        exists, it is returned unchanged (no duplicate write).
        """
        for existing in self._records.values():
            if existing.raw_hash == record.raw_hash:
                return existing  # content-addressed dedup

        record.record_id = f"rec-{len(self._records):06d}"
        self._records[record.record_id] = record
        if self._path:
            self._save()
        return record

    def get(self, record_id: str) -> DomainRecord | None:
        """Return the record for *record_id*, or ``None``."""
        return self._records.get(record_id)

    def list_by_subject(self, subject: str) -> list[DomainRecord]:
        """Return all records whose ``subject`` matches *subject* exactly."""
        return [r for r in self._records.values() if r.subject == subject]

    def all_records(self) -> list[DomainRecord]:
        """Return all stored records in insertion order."""
        return list(self._records.values())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _save(self) -> None:
        assert self._path
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(
                {k: asdict(v) for k, v in self._records.items()},
                fh,
                indent=2,
            )

    def _load(self) -> None:
        assert self._path
        with open(self._path, encoding="utf-8") as fh:
            raw = json.load(fh)
        for rid, data in raw.items():
            self._records[rid] = DomainRecord(**data)


# ---------------------------------------------------------------------------
# Example scorer — replace with your domain's confidence/relevance logic
# ---------------------------------------------------------------------------

_RELIABILITY_WEIGHTS: dict[str, float] = {
    # Adjust or replace entirely for your domain.
    "A": 1.0,
    "B": 0.8,
    "C": 0.6,
    "D": 0.4,
    "E": 0.2,
    "F": 0.0,
    "high": 1.0,
    "medium": 0.6,
    "low": 0.2,
}


def score_record(record: DomainRecord) -> float:
    """Compute a normalized [0, 1] score for *record* and store it in-place.

    This is a stub — replace with your domain's actual scoring model.
    Right now it just maps source_reliability to a weight and returns it.

    Args:
        record: The record to score.  ``record.score`` is updated in-place.

    Returns:
        The computed score.
    """
    weight = _RELIABILITY_WEIGHTS.get(record.source_reliability, 0.5)
    # TODO: combine with payload-specific signals for your domain.
    record.score = weight
    return record.score
