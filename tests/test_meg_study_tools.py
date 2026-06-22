"""Offline tests for wiring the meg_validation study type into the agent tools.

Mirrors test_study_tools.py: loads the plugin, creates a kind='meg_validation'
study via matilde_study_create with params (dataset id, expected window, sample
bounds), and asserts the study runs through the meg_validation dispatch in
matilde_study_run. The real run path is lazy-mne; this test injects a FAKE io via
the module-level test hook so it stays stdlib-only (no mne / network / data).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# Import as a real package first so matilde_plugin is registered in sys.modules
# (mirrors test_meg_study.py); _load_plugin then re-execs the same package name.
import matilde_plugin  # noqa: E402,F401


def _load_plugin():
    path = os.path.join(ROOT, "matilde_plugin", "__init__.py")
    spec = importlib.util.spec_from_file_location("matilde_plugin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeIO:
    """Minimal fake satisfying the MegIO contract for the tools dispatch test."""

    def fetch_sample(self, *, dataset_id, bounds):
        return {"path": "/tmp/fake_raw.fif", "dataset_id": dataset_id,
                "bounds": dict(bounds)}

    def preprocess(self, raw, *, l_freq, h_freq):
        return {"path": "/tmp/fake_filt.fif", "filtered": [l_freq, h_freq]}

    def epoch(self, filtered, *, tmin, tmax):
        return {"path": "/tmp/fake_epo.fif", "n_epochs": 30,
                "window": [tmin, tmax]}

    def evoked(self, epochs):
        return {"path": "/tmp/fake_ave.fif", "n_epochs": 30}

    def measure_peak(self, evoked, *, window_ms):
        return {"latency_ms": 100.0, "amplitude": 4.0, "n_epochs": 30}


def test_meg_study_create_and_run(monkeypatch, tmp_path):
    plugin = _load_plugin()
    monkeypatch.setenv("MATILDE_STUDY_DB", str(tmp_path / "s.db"))

    # Inject the fake io for the meg_validation dispatch (the test hook keeps the
    # tools layer stdlib-only — production uses the real lazy-mne backend).
    from matilde_plugin.engine import meg_study
    monkeypatch.setattr(meg_study, "_TEST_IO", _FakeIO(), raising=False)

    created = json.loads(plugin._handle_study_create({
        "slug": "m100-study",
        "title": "M100 validation",
        "kind": "meg_validation",
        "dataset_id": "bst_auditory",
        "expected_window_ms": [80, 120],
        "bounds": {"crop_tmax": 9.0},
    }))
    assert created["success"] is True
    sid = created["study_id"]
    # A default plan was filled in for meg_validation.
    assert created["plan"] == ["fetch_sample", "preprocess", "epoch",
                               "evoked", "validate_finding"]

    out = json.loads(plugin._handle_study_run({"study_id": str(sid)}))
    assert out["success"] is True, out
    assert out["status"] == "done"

    status = json.loads(plugin._handle_study_status({"study_id": sid}))
    assert status["finding_count"] == 1
    assert status["findings"][0]["verdict"] == "supported"
    assert status["findings"][0]["evidence"]["latency_ms"] == 100.0
