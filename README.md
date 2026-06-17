# Matilde — an AI research assistant for academia & science

**Matilde is an academic and scientific research assistant** — an AI agent package
for working scientists, researchers, and scholars. It helps you **verify and manage
citations**, reason over open research datasets, and (on the roadmap) draft and
check manuscripts. Its flagship capability is a **verifiable-citations engine** that
catches hallucinated, mismatched, and retracted references before they reach a paper.

> **What "Matilde" is, for search:** an open, science/academia use-case
> package for the Hermes agent framework. Keywords: citation verification, hallucinated references,
> retraction checking, Crossref / OpenAlex / DataCite, reproducibility, OpenNeuro /
> BIDS, academic writing. The name is a person's name; the tool is a research
> assistant.

---

## Why citations first

Large language models — and "deep research" agents especially — fabricate
references at alarming rates. A 2026 University of Pennsylvania study found
deep-research agents hallucinate references at **10.7%** versus **4.8%** for plain
search-augmented models. An agent that drafts scientific writing *without* a
verification loop actively makes the problem worse. Matilde's verifier is that loop.

## The verifiable-citations engine

A citation is checked along **four independent axes**:

| Axis | Question | How |
|---|---|---|
| **Existence** | Does the work actually exist? | Crossref → OpenAlex → DataCite (multi-source, so real arXiv/Zenodo/preprint DOIs are never mislabeled "fabricated") |
| **Metadata-match** | Do title / authors / year agree? | fuzzy title match + author-surname overlap + year check |
| **Retraction** | Has it been retracted? | Crossref's Retraction Watch data + OpenAlex `is_retracted` |
| **URL-liveness** | If a URL is cited, does it resolve? | HTTP check with an Internet Archive (Wayback) fallback |

Each citation gets a composite **verifiability score (0–1)** and a **verdict**:
`verified` · `warnings` · `retracted` · `not_found` · `unverifiable`.

### Honest scope: *verifiable*, not *provably correct*

There is no formal proof that a citation is "correct." Axes 1–3 above are
near-deterministic and reliable today. The hardest axis — **claim-support
grounding** (does the cited passage actually substantiate the sentence that cites
it?) — is irreducibly probabilistic and is planned for **v2** (GROBID for PDF
parsing + a SciFact/SemanticCite-style classifier). Matilde reports a confidence
score and an evidence trail, never a false certainty.

## Tools the agent gets

| Tool | What it does |
|---|---|
| `matilde_verify_citation` | Verify one reference (any of: doi, title, authors, year, url) → verdict + score + per-axis detail |
| `matilde_verify_bibliography` | Verify a whole reference list → per-item verdicts + a summary + the items that need attention |
| `matilde_check_retraction` | Quick retraction-only check by DOI |
| `matilde_openneuro_dataset_info` | Metadata for an OpenNeuro dataset (title, authors, modalities, subjects, tasks, size) |
| `matilde_openneuro_search` | List OpenNeuro dataset IDs to discover brain-imaging datasets |
| `matilde_openneuro_list_files` | List a dataset's files with sizes and direct download URLs |

No API keys required — Crossref, OpenAlex, and DataCite are free and
unauthenticated. Optionally set `MATILDE_CONTACT_EMAIL` to join the providers'
polite pools.

## Try it

```python
from matilde_plugin.engine.citations import Reference, verify_reference

ref = Reference(title="Attention Is All You Need",
                authors=["Vaswani", "Shazeer"], year=2017,
                doi="10.48550/arXiv.1706.03762")
result = verify_reference(ref)
print(result.verdict, result.score)   # -> e.g. "verified" 1.0
```

### Command line — verify a whole bibliography

```bash
python3 -m matilde_plugin.engine.cli refs.bib                  # verify a BibTeX file
python3 -m matilde_plugin.engine.cli dois.txt                  # or a list of DOIs (one per line)
python3 -m matilde_plugin.engine.cli --doi 10.1038/171737a0    # or a single DOI
python3 -m matilde_plugin.engine.cli refs.bib --json           # machine-readable
```

Output for a mixed bibliography:

```
Verified 3 reference(s):
  [OK ] verified      0.9  Molecular structure of nucleic acids
  [RET] retracted     0.1  Ileal-lymphoid-nodular hyperplasia
  [XX ] not_found     0.1  A Totally Fabricated Paper

not_found=1  retracted=1  verified=1
```

Exit code is non-zero if any reference is `not_found` or `retracted` — so you can
drop it into CI or a pre-commit hook on a manuscript's `.bib`.

### Tests

```bash
python3 -m pytest tests/ --ignore=tests/test_citations_integration.py   # offline unit suite
MATILDE_LIVE=1 python3 -m pytest tests/test_citations_integration.py    # live API checks
```

## Roadmap

Matilde grows outward from citations toward a full scientific research assistant:

- **Neuroscience / OpenNeuro** — *discovery shipped* ✅: search datasets, read metadata,
  list/download files over the public GraphQL API + S3 (stdlib-only, no datalad needed).
  *Next:* BIDS-compliance validation, then heavier analysis (fMRIPrep, NiMARE
  meta-analysis) behind the Docker layer.
- **v2 — claim-support grounding**: GROBID PDF→TEI + SciFact/SemanticCite passage-level
  "does the source actually support this claim?"
- **Meta-science**: statistical re-checking of published results (statcheck, GRIM/SPRITE,
  p-curve) to flag reporting inconsistencies.
- **Manuscript writing → LaTeX**: draft in Google Docs (multiplayer), convert via
  Pandoc/Quarto, with citation management wired to CSL/`.bib`.
- **Autonomous mode (aspirational)**: scheduled agents that attempt to replicate or
  invalidate existing studies and surface novel leads.

## Architecture & layout

Matilde is built on the Hermes use-case-package template: a plugin + a skill + a soul,
runnable standalone or managed via HSM. The engine lives **inside** the plugin
(`matilde_plugin/engine/`) so the plugin directory is a self-contained, copyable
artifact. See the template's docs for the privacy model, sanitization gate, and
promotion flow.

| Path | What it is |
|------|-----------|
| `matilde_plugin/` | Self-contained Hermes plugin — tool definitions **plus** the bundled engine |
| `matilde_plugin/engine/citations.py` | The verifiable-citations engine (the core; the part we may open-source standalone) |
| `matilde_plugin/engine/openneuro.py` | Read-only OpenNeuro/BIDS client — discovery, metadata, files (stdlib-only) |
| `matilde_plugin/engine/parsing.py` · `matilde_plugin/engine/cli.py` | BibTeX/DOI ingestion + the `matilde` verify CLI (`python3 -m matilde_plugin.engine.cli`) |
| `hermes-skill/SKILL.md` | The agent's research methodology |
| `docker/SOUL.Matilde.md` | The research-assistant identity |
| `tests/` | Offline unit suite + live API integration tests |

---

*Matilde is private during development. The citation engine is intended for the public
commons once it has proven itself — promoted through the template's sanitization gate.*
