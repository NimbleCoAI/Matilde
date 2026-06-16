# Matilde — an AI research assistant for academia & science

**Matilde is an academic and scientific research assistant** — an AI agent package
for working scientists, researchers, and scholars. It helps you **verify and manage
citations**, reason over open research datasets, and (on the roadmap) draft and
check manuscripts. Its flagship capability is a **verifiable-citations engine** that
catches hallucinated, mismatched, and retracted references before they reach a paper.

> **What "Matilde" is, for search:** an open, science/academia use-case
> customization of the [Egregore](https://github.com/egregore-labs/egregore) /
> Hermes agent framework. Keywords: citation verification, hallucinated references,
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

No API keys required — Crossref, OpenAlex, and DataCite are free and
unauthenticated. Optionally set `MATILDE_CONTACT_EMAIL` to join the providers'
polite pools.

## Try it

```python
from engine.citations import Reference, verify_reference

ref = Reference(title="Attention Is All You Need",
                authors=["Vaswani", "Shazeer"], year=2017,
                doi="10.48550/arXiv.1706.03762")
result = verify_reference(ref)
print(result.verdict, result.score)   # -> e.g. "verified" 1.0
```

```bash
python3 -m pytest tests/ --ignore=tests/test_citations_integration.py   # offline unit suite
MATILDE_LIVE=1 python3 -m pytest tests/test_citations_integration.py    # live API checks
```

## Roadmap

Matilde grows outward from citations toward a full scientific research assistant:

- **v2 — claim-support grounding**: GROBID PDF→TEI + SciFact/SemanticCite passage-level
  "does the source actually support this claim?"
- **Neuroscience / OpenNeuro**: pull and reason over [OpenNeuro](https://openneuro.org)
  / BIDS datasets (openneuro-py, DataLad, NiMARE); validate, analyze, replicate.
- **Meta-science**: statistical re-checking of published results (statcheck, GRIM/SPRITE,
  p-curve) to flag reporting inconsistencies.
- **Manuscript writing → LaTeX**: draft in Google Docs (multiplayer), convert via
  Pandoc/Quarto, with citation management wired to CSL/`.bib`.
- **Autonomous mode (aspirational)**: scheduled agents that attempt to replicate or
  invalidate existing studies and surface novel leads.

## Architecture & layout

Matilde is built on the Hermes use-case-package template: a plugin + a skill + a soul
+ an engine, runnable standalone or managed via HSM. See the template's docs for the
privacy model, sanitization gate, and promotion flow.

| Path | What it is |
|------|-----------|
| `engine/citations.py` | The verifiable-citations engine (the core; the part we may open-source standalone) |
| `hermes-plugin/` | Hermes tool definitions exposing the engine to the agent |
| `hermes-skill/SKILL.md` | The agent's research methodology |
| `docker/SOUL.Matilde.md` | The research-assistant identity |
| `tests/` | Offline unit suite + live API integration tests |

---

*Matilde is private during development. The citation engine is intended for the public
commons once it has proven itself — promoted through the template's sanitization gate.*
