"""Tests for the MEG data-sample validation study (the M100 worked claim).

The whole study is exercised with FAKES — no mne, no numpy, no network, no data
files. Each step takes injected loader/analysis callables, so the unit tests are
deterministic and stdlib-only. Covered here:

  - each step transforms the study state correctly (fetch -> preprocess -> epoch
    -> evoked -> validate_finding), reading prior-step data and persisting an
    artifact per heavy step;
  - the ``validate_finding`` verdict boundaries — peak at 100 ms -> supported,
    peak at 300 ms -> refuted, empty/degenerate sample -> inconclusive;
  - resumability — force a failure at the ``evoked`` step, assert the study is
    blocked with the earlier steps done, then resume with a working analyzer and
    assert fetch/preprocess/epoch are NOT re-run (call counters).

An opt-in live test (``MATILDE_LIVE=1`` and mne importable) runs the real bounded
pipeline on ``bst_auditory`` — it SKIPS without the flag / without mne.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from matilde_plugin.engine.meg_study import (  # noqa: E402
    MegIO,
    _peak_search_bounds,
    build_steps,
)
from matilde_plugin.engine.pipeline import resume, run  # noqa: E402
from matilde_plugin.engine.store import StudyStore  # noqa: E402


# ---------------------------------------------------------------------------
# A fake MEG I/O backend: pure dicts, deterministic, counts each call so the
# resumability test can prove done steps are not re-run. No mne / numpy / fs.
# ---------------------------------------------------------------------------

class FakeMegIO:
    """Stand-in for the real (lazy mne) I/O. Each method bumps a counter and
    returns a small dict 'handle' threaded through the steps."""

    def __init__(self, *, peak_latency_ms=100.0, peak_amp=5.0, n_epochs=40,
                 fail_evoked=False):
        self.peak_latency_ms = peak_latency_ms
        self.peak_amp = peak_amp
        self.n_epochs = n_epochs
        self.fail_evoked = fail_evoked
        self.calls = {"fetch": 0, "preprocess": 0, "epoch": 0, "evoked": 0,
                      "measure_peak": 0}
        # Records the event_id the study asked epoch to filter to (None=all).
        self.epoch_event_id = "__unset__"

    def fetch_sample(self, *, dataset_id, bounds):
        self.calls["fetch"] += 1
        return {"dataset_id": dataset_id, "bounds": dict(bounds),
                "path": "/tmp/fake_raw.fif"}

    def preprocess(self, raw, *, l_freq, h_freq):
        self.calls["preprocess"] += 1
        return {**raw, "filtered": [l_freq, h_freq], "path": "/tmp/fake_filt.fif"}

    def epoch(self, filtered, *, tmin, tmax, event_id=None):
        self.calls["epoch"] += 1
        self.epoch_event_id = event_id
        return {**filtered, "n_epochs": self.n_epochs,
                "window": [tmin, tmax], "path": "/tmp/fake_epo.fif"}

    def evoked(self, epochs):
        self.calls["evoked"] += 1
        if self.fail_evoked:
            raise RuntimeError("OOM while averaging evoked response")
        return {**epochs, "averaged": True, "path": "/tmp/fake_ave.fif"}

    def measure_peak(self, evoked, *, window_ms):
        self.calls["measure_peak"] += 1
        if self.n_epochs <= 0:  # degenerate sample -> no measurable peak
            return {"latency_ms": None, "amplitude": None, "n_epochs": 0}
        return {"latency_ms": self.peak_latency_ms, "amplitude": self.peak_amp,
                "n_epochs": self.n_epochs}


@pytest.fixture()
def store(tmp_path):
    return StudyStore(str(tmp_path / "studies.db"))


def _plan():
    return ["fetch_sample", "preprocess", "epoch", "evoked", "validate_finding"]


# ---------------------------------------------------------------------------
# MegIO is a Protocol-ish contract; the fake should satisfy it (sanity).
# ---------------------------------------------------------------------------

def test_fakeio_satisfies_contract():
    io = FakeMegIO()
    assert isinstance(io, MegIO)


# ---------------------------------------------------------------------------
# Regression: the peak-search bounds must stay WITHIN the expected window.
#
# The original bug widened the search by +/-100 ms, so an 80-120 ms M100 window
# became a ~-20..220 ms search that grabbed the large ~15 ms stimulus artifact
# instead of the real ~100 ms auditory peak (reported 15 ms -> "refuted"). This
# pure, mne-free helper is the unit that would have caught it.
# ---------------------------------------------------------------------------

def test_peak_search_bounds_stay_in_window_not_widened_by_100ms():
    # Wide available times (e.g. -0.1 .. 0.3 s) must NOT let the search escape
    # the expected window. For an 80-120 ms window we expect ~0.08..0.12 s,
    # never the -0.02..0.22 s that the +/-100 ms bug produced.
    lo, hi = _peak_search_bounds((80.0, 120.0), times_lo=-0.1, times_hi=0.3)
    # A small symmetric margin is allowed, but nothing near +/-100 ms.
    assert lo >= 0.06 and lo <= 0.08, lo      # not -0.02
    assert hi >= 0.12 and hi <= 0.14, hi      # not 0.22
    # And explicitly: the early stimulus artifact at ~15 ms is OUTSIDE the search.
    assert lo > 0.015


def test_peak_search_bounds_clamped_to_available_times():
    # If the recording is shorter than the window, clamp to available samples.
    lo, hi = _peak_search_bounds((80.0, 120.0), times_lo=0.09, times_hi=0.11)
    assert lo == 0.09
    assert hi == 0.11


# ---------------------------------------------------------------------------
# Regression: epoch must filter to the standard-tone event by default, not
# average ALL triggers (standards + deviants + button presses), which muddied
# the evoked average in the live run.
# ---------------------------------------------------------------------------

def test_epoch_applies_standards_event_filter_by_default(store):
    sid = store.create_study(slug="evfilter", title="EvFilter", plan=_plan())
    io = FakeMegIO()
    run(store, sid, build_steps(dataset_id="bst_auditory", io=io))
    # The study must NOT ask epoch to average every trigger. The default is the
    # standards-only auto filter (event_id=None -> most-frequent code, resolved
    # inside the real backend), never the "all events" sentinel that produced
    # the muddied average behind the original mis-measurement.
    assert io.epoch_event_id != "__unset__", "epoch was never called"
    assert io.epoch_event_id != "all", (
        "epoch was told to average ALL triggers -> muddied evoked average")
    assert io.epoch_event_id is None, (
        "default should be the auto standards filter (None), resolved in backend")


def test_epoch_event_id_overridable_via_bounds(store):
    sid = store.create_study(slug="evfilter2", title="EvFilter2", plan=_plan())
    io = FakeMegIO()
    run(store, sid, build_steps(dataset_id="bst_auditory", io=io,
                                bounds={"event_id": 7}))
    assert io.epoch_event_id == 7


# ---------------------------------------------------------------------------
# Happy path — peak at 100 ms is within the default 80-120 window -> supported.
# ---------------------------------------------------------------------------

def test_happy_path_peak_within_window_is_supported(store):
    sid = store.create_study(slug="m100", title="M100", plan=_plan())
    io = FakeMegIO(peak_latency_ms=100.0)
    steps = build_steps(dataset_id="bst_auditory", io=io)
    summary = run(store, sid, steps)

    assert summary["status"] == "done"
    assert store.get_study(sid)["status"] == "done"

    findings = store.get_findings(sid)
    assert len(findings) == 1
    f = findings[0]
    assert f["verdict"] == "supported"
    assert f["evidence"]["latency_ms"] == 100.0
    assert f["evidence"]["amplitude"] == 5.0

    # each heavy step checkpointed an artifact (resume-after-OOM target)
    arts = {a["step_name"] for a in store.get_artifacts(sid)}
    assert {"fetch_sample", "preprocess", "epoch", "evoked"} <= arts


# ---------------------------------------------------------------------------
# Verdict boundaries.
# ---------------------------------------------------------------------------

def test_peak_far_outside_window_is_refuted(store):
    sid = store.create_study(slug="r", title="R", plan=_plan())
    io = FakeMegIO(peak_latency_ms=300.0)
    run(store, sid, build_steps(dataset_id="bst_auditory", io=io))
    f = store.get_findings(sid)[0]
    assert f["verdict"] == "refuted"
    assert f["evidence"]["latency_ms"] == 300.0


def test_degenerate_sample_is_inconclusive(store):
    sid = store.create_study(slug="i", title="I", plan=_plan())
    io = FakeMegIO(n_epochs=0)  # no epochs -> no measurable peak
    run(store, sid, build_steps(dataset_id="bst_auditory", io=io))
    f = store.get_findings(sid)[0]
    assert f["verdict"] == "inconclusive"
    assert f["evidence"]["latency_ms"] is None


def test_custom_window_changes_verdict(store):
    """A peak at 150 ms is refuted under default (80-120) but supported under a
    wider custom window — proves the expected-window param is honored."""
    sid = store.create_study(slug="w", title="W", plan=_plan())
    io = FakeMegIO(peak_latency_ms=150.0)
    run(store, sid, build_steps(dataset_id="bst_auditory", io=io,
                                expected_window_ms=(130.0, 170.0)))
    assert store.get_findings(sid)[0]["verdict"] == "supported"


# ---------------------------------------------------------------------------
# Step state transitions — each step's data threads into the next.
# ---------------------------------------------------------------------------

def test_steps_thread_state_forward(store):
    sid = store.create_study(slug="t", title="T", plan=_plan())
    io = FakeMegIO()
    run(store, sid, build_steps(dataset_id="bst_auditory", io=io,
                                bounds={"crop_tmax": 9.0}))

    # bounds flowed into the fetch handle and the artifact meta.
    fetch_res = store.get_step(sid, "fetch_sample")["result"]
    assert fetch_res["dataset_id"] == "bst_auditory"
    assert fetch_res["bounds"]["crop_tmax"] == 9.0

    epoch_res = store.get_step(sid, "epoch")["result"]
    assert epoch_res["n_epochs"] == 40

    evoked_res = store.get_step(sid, "evoked")["result"]
    assert evoked_res["n_epochs"] == 40


# ---------------------------------------------------------------------------
# Resumability — fail at evoked, resume, earlier steps not re-run.
# ---------------------------------------------------------------------------

def test_fail_at_evoked_then_resume_does_not_rerun_earlier_steps(store):
    sid = store.create_study(slug="resume", title="Resume", plan=_plan())

    # First pass: evoked raises (simulated OOM mid-average).
    failing_io = FakeMegIO(fail_evoked=True)
    run(store, sid, build_steps(dataset_id="bst_auditory", io=failing_io))

    assert store.get_step(sid, "fetch_sample")["status"] == "done"
    assert store.get_step(sid, "preprocess")["status"] == "done"
    assert store.get_step(sid, "epoch")["status"] == "done"
    assert store.get_step(sid, "evoked")["status"] == "failed"
    assert store.get_step(sid, "validate_finding")["status"] == "pending"
    assert store.get_study(sid)["status"] in ("blocked", "failed")
    assert store.get_findings(sid) == []  # no finding emitted yet

    assert failing_io.calls["fetch"] == 1
    assert failing_io.calls["preprocess"] == 1
    assert failing_io.calls["epoch"] == 1
    assert failing_io.calls["evoked"] == 1  # attempted, raised

    # Second pass: working io, resume.
    good_io = FakeMegIO(fail_evoked=False, peak_latency_ms=100.0)
    resume(store, sid, build_steps(dataset_id="bst_auditory", io=good_io))

    assert store.get_study(sid)["status"] == "done"
    # Earlier (done) steps were NOT re-run on the working io.
    assert good_io.calls["fetch"] == 0
    assert good_io.calls["preprocess"] == 0
    assert good_io.calls["epoch"] == 0
    # Only the previously-failed step + the remaining step ran.
    assert good_io.calls["evoked"] == 1
    assert good_io.calls["measure_peak"] == 1

    f = store.get_findings(sid)[0]
    assert f["verdict"] == "supported"


# ---------------------------------------------------------------------------
# Opt-in LIVE test — real bounded mne pipeline. SKIPS without flag / mne.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.environ.get("MATILDE_LIVE") != "1",
                    reason="live MEG test is opt-in (set MATILDE_LIVE=1)")
def test_live_bst_auditory_m100_bounded():
    pytest.importorskip("mne")
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = StudyStore(os.path.join(tmp, "studies.db"))
        sid = store.create_study(slug="live-m100", title="Live M100",
                                 plan=_plan())
        # Default io=None -> the real, memory-bounded mne backend.
        steps = build_steps(dataset_id="bst_auditory")
        summary = run(store, sid, steps)

        assert summary["status"] == "done", summary
        f = store.get_findings(sid)[0]
        # A plausible auditory peak should be found and measured.
        assert f["evidence"]["latency_ms"] is not None
        assert 50.0 <= f["evidence"]["latency_ms"] <= 200.0
        assert f["verdict"] in ("supported", "refuted")
