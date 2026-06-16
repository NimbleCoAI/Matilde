"""Example collector — fill this in for your first real data source.

Copy this file, rename it to ``<source_name>_collector.py``, and replace every
``# TODO`` comment with real logic.  Delete this file once you have at least
one production collector.

This module registers itself at import time.  Import it (or auto-discover the
``collectors/`` package) in your skill entry point so the registry is populated.
"""
from __future__ import annotations

import json
from typing import Any

from example_collectors.base import (
    CollectionResult,
    Collector,
    register_collector,
)


class ExampleCollector:
    """Stub collector for {{SOURCE_NAME}}.

    Replace the class name, ``name``, ``source_reliability``, and ``collect``
    body with real implementation.

    Attributes
    ----------
    name : str
        Machine-readable identifier used in audit logs and the registry.
        Convention: ``<source_slug>`` all-lowercase, underscores.

    source_reliability : str
        Grade for this source.  Use A–F or high/medium/low — whichever your
        ``engine.score_record`` implementation expects.
    """

    name: str = "{{SOURCE_SLUG}}"          # e.g. "my_api_v2"
    source_reliability: str = "medium"     # A–F or high/medium/low

    # TODO: Add __init__ if you need to inject credentials or a base URL.
    # def __init__(self, api_key: str, base_url: str = "https://...") -> None:
    #     self._api_key = api_key
    #     self._base_url = base_url

    def collect(self, query: str, **params: Any) -> CollectionResult:
        """Query {{SOURCE_NAME}} for *query* and return structured results.

        Args:
            query: The primary search term.  For this source that means:
                   TODO — describe what query represents (a name, URL, ID, …).
            **params: TODO — document source-specific params here.
                      e.g. ``limit`` (int, max results), ``after`` (cursor str).

        Returns:
            A ``CollectionResult`` with:
              - ``raw_response``: raw JSON/bytes from the source
              - ``candidate_entities``: extracted entity dicts
              - ``candidate_items``: extracted domain item dicts
              - ``metadata``: provenance (query, source version, …)

        Raises:
            RuntimeError: TODO — map HTTP/IO errors to a domain exception.
        """
        # ------------------------------------------------------------------
        # TODO: Replace the stub below with a real HTTP call or SDK call.
        # ------------------------------------------------------------------

        # Stub: synthesize an empty response so the package is importable
        # and the skill can call collect() in dry-run / unit-test mode.
        stub_payload: dict[str, Any] = {
            "query": query,
            "results": [],
            # Add source-specific fields here once you wire the real API.
        }
        raw_bytes = json.dumps(stub_payload).encode("utf-8")

        # TODO: Parse ``raw_bytes`` into real entities and items.
        candidate_entities: list[dict[str, Any]] = [
            # {"name": "...", "type": "...", "identifiers": {...}}
        ]
        candidate_items: list[dict[str, Any]] = [
            # {"item_text": "...", "confidence": 0.9, "entity_index": 0}
        ]

        return CollectionResult(
            raw_response=raw_bytes,
            content_type="application/json",
            candidate_entities=candidate_entities,
            candidate_items=candidate_items,
            metadata={
                "query": query,
                "source": self.name,
                "params": params,
                # TODO: add pagination cursors, response headers, etc.
            },
        )


# Register so the skill can discover this collector by name.
# Keep this at module level — it runs on import.
register_collector(ExampleCollector.name, ExampleCollector)


# Satisfy the structural protocol at import time (catches missing attrs/methods).
_: Collector = ExampleCollector()  # type: ignore[assignment]
