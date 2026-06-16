"""Live OpenNeuro integration tests — hit the real GraphQL API + S3.

Skipped unless ``MATILDE_LIVE=1``. Guards the GraphQL schema assumptions against
API drift, using the stable public dataset ds000246.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from engine.openneuro import get_dataset, list_datasets, list_files  # noqa: E402

LIVE = os.environ.get("MATILDE_LIVE") == "1"
pytestmark = pytest.mark.skipif(not LIVE, reason="set MATILDE_LIVE=1 to run live API tests")


def test_live_get_dataset_metadata():
    ds = get_dataset("ds000246")
    assert ds.id == "ds000246"
    assert "meg" in [m.lower() for m in ds.modalities]
    assert ds.name                      # has a human title
    assert ds.size and ds.size > 0
    assert ds.latest_tag                # has a snapshot tag


def test_live_list_datasets():
    ids = list_datasets(limit=3)
    assert len(ids) == 3
    assert all(i.startswith("ds") for i in ids)


def test_live_list_files_has_description():
    files = list_files("ds000246")
    names = [f["filename"] for f in files]
    assert "dataset_description.json" in names
    desc = next(f for f in files if f["filename"] == "dataset_description.json")
    assert desc["url"].startswith("https://s3.amazonaws.com/openneuro.org/")
