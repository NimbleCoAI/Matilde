"""Tests for the OpenNeuro client (discovery / metadata / files / download).

GraphQL and HTTP are injected, so these run offline. The canned responses mirror
the REAL OpenNeuro GraphQL shapes, validated live against ds000246.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from matilde_plugin.engine.openneuro import (  # noqa: E402
    Dataset,
    OpenNeuroError,
    download_file,
    get_dataset,
    list_datasets,
    list_files,
)

# Real GraphQL response shape for dataset(id:"ds000246").
DATASET_RESP = {
    "dataset": {
        "id": "ds000246",
        "created": "2018-03-30T10:34:05.130Z",
        "public": True,
        "latestSnapshot": {
            "tag": "1.0.1",
            "created": "2024-04-23T10:17:01.000Z",
            "size": 2457671893,
            "description": {
                "Name": "MEG-BIDS Brainstorm data sample",
                "Authors": ["Elizabeth Bock", "Francois Tadel"],
            },
            "summary": {"subjects": ["0001"], "modalities": ["meg", "mri"], "tasks": ["AEF", "noise"]},
        },
    }
}

DATASETS_RESP = {
    "datasets": {"edges": [
        {"node": {"id": "ds000001"}},
        {"node": {"id": "ds000002"}},
        {"node": {"id": "ds000003"}},
    ]}
}

SNAPSHOT_FILES_RESP = {
    "snapshot": {
        "id": "ds000246:1.0.1",
        "files": [
            {"filename": "dataset_description.json", "size": 958,
             "urls": ["https://s3.amazonaws.com/openneuro.org/ds000246/dataset_description.json?versionId=abc"]},
            {"filename": "README", "size": 5990,
             "urls": ["https://s3.amazonaws.com/openneuro.org/ds000246/README?versionId=def"]},
        ],
    }
}


def make_gql(routes):
    """Return a gql(query, variables)->data that picks a response by substring."""
    def _gql(query, variables=None):
        for needle, resp in routes.items():
            if needle in query:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"no canned response for query: {query[:60]}")
    return _gql


# ---------------------------------------------------------------------------
# get_dataset
# ---------------------------------------------------------------------------

def test_get_dataset_parses_metadata():
    ds = get_dataset("ds000246", gql=make_gql({"dataset(": DATASET_RESP}))
    assert isinstance(ds, Dataset)
    assert ds.id == "ds000246"
    assert ds.name == "MEG-BIDS Brainstorm data sample"
    assert ds.modalities == ["meg", "mri"]
    assert ds.subjects == ["0001"]
    assert ds.tasks == ["AEF", "noise"]
    assert ds.latest_tag == "1.0.1"
    assert ds.size == 2457671893
    assert "Elizabeth Bock" in ds.authors


def test_get_dataset_missing_raises():
    gql = make_gql({"dataset(": {"dataset": None}})
    with pytest.raises(OpenNeuroError):
        get_dataset("ds999999", gql=gql)


def test_get_dataset_to_dict_is_json_safe():
    import json
    ds = get_dataset("ds000246", gql=make_gql({"dataset(": DATASET_RESP}))
    json.dumps(ds.to_dict())


# ---------------------------------------------------------------------------
# list_datasets
# ---------------------------------------------------------------------------

def test_list_datasets_returns_ids():
    ids = list_datasets(limit=3, gql=make_gql({"datasets(": DATASETS_RESP}))
    assert ids == ["ds000001", "ds000002", "ds000003"]


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------

def test_list_files_returns_name_size_url():
    files = list_files("ds000246", gql=make_gql({"snapshot(": SNAPSHOT_FILES_RESP,
                                                 "dataset(": DATASET_RESP}))
    assert files[0]["filename"] == "dataset_description.json"
    assert files[0]["size"] == 958
    assert files[0]["url"].startswith("https://s3.amazonaws.com/openneuro.org/")


def test_list_files_uses_latest_tag_when_none_given():
    # When tag is omitted, the client must resolve the latest tag from the dataset.
    seen = {}

    def gql(query, variables=None):
        if "dataset(" in query and "snapshot" not in query:
            return DATASET_RESP
        if "snapshot(" in query:
            seen["vars"] = variables
            return SNAPSHOT_FILES_RESP
        raise AssertionError(query[:40])

    list_files("ds000246", gql=gql)
    assert seen["vars"]["tag"] == "1.0.1"


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------

def test_download_file_writes_bytes(tmp_path):
    dest = tmp_path / "dataset_description.json"
    captured = {}

    def http_get(url):
        captured["url"] = url
        return b'{"Name": "MEG-BIDS Brainstorm data sample"}'

    gql = make_gql({"snapshot(": SNAPSHOT_FILES_RESP, "dataset(": DATASET_RESP})
    path = download_file("ds000246", "dataset_description.json", str(dest),
                         gql=gql, http_get=http_get)
    assert os.path.exists(path)
    assert b"Brainstorm" in open(path, "rb").read()
    assert captured["url"].startswith("https://s3.amazonaws.com/openneuro.org/")


def test_download_file_unknown_filename_raises(tmp_path):
    gql = make_gql({"snapshot(": SNAPSHOT_FILES_RESP, "dataset(": DATASET_RESP})
    with pytest.raises(OpenNeuroError):
        download_file("ds000246", "no_such_file.nii.gz", str(tmp_path / "x"),
                      gql=gql, http_get=lambda u: b"")
