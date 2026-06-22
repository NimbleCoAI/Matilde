# MEG data-sample validation study (design)

Builds on the stateful study pipeline (`docs/stateful-study-pipeline.md`). First
**heavy / real-data** study type: validate a reported neuroscience finding against
a **bounded sample** of an open MEG dataset, as resumable checkpointed steps.

## Why "data sample", not full-dataset

Full-preloading a multi-GB MEG recording into the agent process exhausts container
memory. This study deliberately validates against a **bounded sample** —
enough signal to test the claimed effect, never the whole recording. Combined
with the pipeline's per-step checkpointing, a memory kill or container restart
**resumes from the last completed step** instead of restarting the analysis.

## Worked claim (first target)

The auditory **M100 / N100m** evoked response: a magnetic field peak ~80–120 ms
after an auditory stimulus. Open data: the Brainstorm auditory sample
(`mne.datasets.brainstorm.bst_auditory`, the ds000246 tutorial data) — standard
tones, a well-established M100. The study measures the peak latency of the evoked
response to standard tones and validates it falls within the expected window.

## Steps (resumable; each checkpoints an artifact + may emit a finding)

1. `fetch_sample` — obtain a bounded slice: download/locate the dataset, but load
   **memory-bounded** — `preload=False`, pick one run, a subset of gradiometer
   channels, crop to a stimulus-locked window, and downsample. Persist a small
   intermediate (e.g. epochs/evoked `.npy` or `.fif`) as an artifact; never hold
   the full recording.
2. `preprocess` — band-pass filter (e.g. 1–40 Hz) the bounded sample; checkpoint.
3. `epoch` — epoch around standard-tone events (the analysis must read the events
   from the data, not assume counts); checkpoint epoch metadata.
4. `evoked` — average to the evoked response; checkpoint the evoked array artifact.
5. `validate_finding` — measure peak latency in the M100 window; emit a finding:
   `supported` if within the expected window (default 80–120 ms), `refuted` if
   clearly outside, `inconclusive` if SNR too low / sample too small. Record the
   measured latency + amplitude as evidence.

## Implementation rules (match the repo)

- **Lazy heavy deps**: `mne`/`numpy` imported **inside** the step functions, never
  at module import — the plugin must load (and the rest of the engine stay
  stdlib-only) without mne installed. The agent container already has mne available
  at runtime.
- **Injected I/O for tests**: the step functions take injected loader/analysis
  handles so the whole study is testable with **fakes** (no mne, no network, no
  data) — deterministic, fast, stdlib-only. The real mne path is exercised only at
  runtime and by an **opt-in** live test (`MATILDE_LIVE=1`, skipped in CI).
- **Wire into the framework**: add a `meg_validation` study type the
  `matilde_study_create` plan can request (params: dataset id, expected-window ms,
  channel/sample bounds), runnable via `matilde_study_run` and resumable like any
  study.

## Tests

- Unit (stdlib, fakes): each step's logic; `validate_finding` verdict boundaries
  (within window → supported; far outside → refuted; degenerate sample →
  inconclusive); resumability (fail at `evoked`, resume, earlier steps not re-run).
- Opt-in live (`MATILDE_LIVE=1`): run the real bounded mne pipeline on
  `bst_auditory`, assert a peak is found in a plausible window and the study
  completes `done` within a bounded memory footprint. Skipped without the flag.

## Out of scope (later)

Multi-subject/meta-analysis, source localization, statcheck/GRIM re-checking —
separate study types once this single-finding validation is proven live.
