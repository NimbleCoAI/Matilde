---
name: {{PACKAGE_SLUG}}-methodology
description: {{ONE_SENTENCE_DESCRIPTION_OF_WHAT_THIS_PACKAGE_DOES}}
version: 1.0.0
author: {{AUTHOR_OR_ORG}}
license: {{LICENSE}}
metadata:
  hermes:
    tags: [{{TAG_1}}, {{TAG_2}}, {{TAG_3}}]
    related_skills: []
---

# {{PACKAGE_NAME}} Methodology

{{TWO_TO_THREE_SENTENCE_OVERVIEW: what problem this package solves, what the agent is doing when this skill is active, and what a "done" result looks like for the domain.}}

## Prerequisites

- `{{PACKAGE_SLUG}}-plugin` installed in Hermes (provides the tools listed in each phase below)
- {{CREDENTIAL_1}}: `{{ENV_VAR_NAME}}` — {{what it unlocks}}
- {{CREDENTIAL_2}}: `{{ENV_VAR_NAME}}` — {{what it unlocks}} (optional — {{what degrades without it}})

If no credentials are configured, the agent can still {{describe the no-cred fallback}}.

## Methodology Lifecycle

Every engagement follows this cycle. Do not skip phases — each builds on the previous one.

```
SCOPE → GATHER → ASSESS → ACT → REPORT
  ↑                            |
  └────────────────────────────┘
```

> **Rename these phases.** The labels above are generic starters. Replace them with
> the actual verbs that describe your domain's workflow — for example: SCOPE → SEED →
> COLLECT → RESOLVE → CORROBORATE → TRIM → PUBLISH, or BRIEF → RESEARCH → SYNTHESIZE →
> RECOMMEND → DELIVER. The structure (linear with feedback loop) is what matters; the
> names should be obvious to a practitioner in your field.

### Phase 1: Scope

Before doing anything, define what this engagement is about and what a satisfactory answer looks like.

```
{{TOOL_create}}(action="create", name="{{Descriptive Name}}", slug="{{url-safe-slug}}", scope="{{What and why}}")
```

A clear scope prevents drift. Write it as if someone else will read it a week later and need to resume without you.

### Phase 2: Gather

Run the package's collectors/tools against your starting inputs. The plugin should:
- Archive raw source material (content-addressed, with provenance)
- Extract structured findings
- Log everything to the engagement record

```
{{TOOL_gather}}(engagement_slug="...", source="{{source_name}}", query="{{input}}")
```

### Phase 3: Assess

After initial gathering, assess what you have: what's well-supported, what's missing, what contradicts.

```
{{TOOL_assess}}(engagement_slug="...", action="gaps")
{{TOOL_assess}}(engagement_slug="...", action="summary")
```

Look for:
- Single-source findings that need corroboration
- Contradictions between sources
- High-confidence items that are still under-explored

### Phase 4: Act (Targeted Work)

Based on the assessment, take targeted action: fill gaps, expand confirmed threads, prune noise.

**Fill a gap:**
```
{{TOOL_gather}}(engagement_slug="...", source="{{targeted_source}}", query="{{gap_query}}")
```

**Prune noise below a confidence threshold:**
```
{{TOOL_trim}}(engagement_slug="...", threshold={{0.0_to_1.0}})
```

This hides low-confidence findings without deleting them. Reversible.

**Expand a confirmed finding outward:**
Run all relevant collectors against the identifiers of a well-confirmed finding. This is how work grows outward from anchored nodes.

### Phase 5: Report

Generate the deliverable in the format appropriate for the engagement.

```
{{TOOL_report}}(engagement_slug="...", format="{{json|markdown|csv|pdf}}")
{{TOOL_report}}(engagement_slug="...", format="markdown", min_confidence={{threshold}})
```

## Iteration Pattern

Good work in this domain is iterative, not linear. The standard loop:

1. **Gather** from known starting points
2. **Assess** — identify gaps and contradictions
3. **Fill gaps** — targeted gathering on weak areas
4. **Prune** — remove noise below confidence threshold
5. **Expand** — follow confirmed leads outward
6. **Repeat** until the gap analysis returns no actionable items at your target confidence level, or until the scope question is answered

An engagement is "done" when you can answer the scope question with evidence that meets your delivery standard, or when you've documented why the question cannot be answered with available sources.

## Novelty / Don't Redo Work

When an engagement is approaching its deliverable, run novelty checks **in parallel with
gathering** — not after. Spawn parallel subagents: one gathering and synthesizing a
thread, one checking whether the key claims are already covered by prior work, existing
reports, or public sources.

This stops you from investing deeply in threads that are already fully handled elsewhere.

For each key claim or finding, determine:

1. Has this already been addressed — by a prior engagement, a public source, or an existing artifact?
2. If yes — do we have something genuinely additional that constitutes a meaningful contribution?
3. If no — is our sourcing strong enough to stand alone?

Track each claim's novelty in one of three buckets:

- **Already covered** — do not lead with these as new. Reference the prior work instead.
- **Partially covered / gap** — possible angles; nail down what specifically is new before committing effort.
- **Potentially original** — verify carefully before treating as confirmed. Check secondary and niche sources, not just the obvious ones: a finding in a low-circulation source is still "known."

A finished deliverable is **grounded in evidence, novel relative to prior work, and tells
a story a non-specialist would find actionable.**

## Session Continuity: The Handoff Pattern

Long, multi-session engagements need explicit continuity infrastructure. The agent cannot
hold working state across sessions natively — this discipline is what replaces it.

Three layers carry state across sessions:

- **Standing-orders document** — what this engagement is, what it values, what the
  current working hypothesis is. Read it at the start of every session. This is
  engagement-specific and lives in the operator's private overlay (`skills/` in
  `HERMES_HOME`), **not** in this shared package. See the extension-point section below.
- **Memory layer** — accumulated findings, resolved questions, and tool quirks kept in
  the agent's persistent memory and in per-engagement reference files.
- **Handoff artifact** — a structured end-of-session summary written by the outgoing
  session, read first by the incoming session.

### What a Handoff Carries

A handoff is not a log dump. It is a cold-start entry point. Write it so a fresh session
can resume in under two minutes without re-deriving everything. A complete handoff
contains:

- **What happened and why** — a brief narrative of what the session did and the
  reasoning behind the key moves. Not a transcript; a digest.
- **Decisions with rationale** — every non-obvious decision made this session, with the
  reason. "I chose source X over Y because..." Future sessions must be able to evaluate
  whether the reason still holds.
- **State per active thread** — for each open line of work: where it stands, what was
  last done, and what the concrete next step is (specific enough to execute without
  context).
- **Open threads with next steps** — explicitly enumerated, each with a next action. Not
  "look into X" but "run {{TOOL_gather}} against {{specific_identifier}} to close the gap
  on {{specific_claim}}."
- **Closed threads with reasons** — what was explored and set aside, and why. Prevents
  the next session from re-opening dead ends.
- **Cold-start entry point** — a single instruction the incoming session can execute
  immediately to get oriented: read a specific artifact, run a specific tool call,
  check a specific status. If the next session has to read the full handoff to know
  where to start, the handoff is too long.

Update the handoff at the end of any significant session with: novelty-assessment
changes, new thread status, methodology lessons, and tool quirks discovered. The same
discipline the evidence trail provides for facts, applied to the engagement's own working
state.

## Quality and Ethics Floor

These apply regardless of domain. Instantiators should add domain-specific guidance in
the operator overlay.

- Use only **legal, permitted** sources and methods
- **Document methodology** for every significant finding — not just what, but how
- **Never fabricate** findings or inflate confidence scores
- **Grade honestly** — overconfident outputs are worse than underconfident ones
- **Preserve raw source material** — the plugin should archive automatically; never
  delete artifacts during an active engagement
- When in doubt about legality or ethics, **stop and consult** before proceeding
- The audit record is your defense — it proves you followed a systematic, reproducible
  methodology

## Extending This Skill: Per-Engagement Overlays

This SKILL.md is the shared, domain-agnostic baseline. It intentionally contains no
engagement-specific particulars — no subject names, no codenames, no engagement-specific
tooling.

Per-engagement customization lives in the **operator's private overlay**:

```
$HERMES_HOME/skills/{{PACKAGE_SLUG}}-{{engagement-slug}}.md
```

This file is **never committed to this repository**. It is covered by the `.gitignore`
patterns `instance/` and `.overlay/` (and by the sanitization gate if you run it before
pushing). The private overlay typically contains:

- The standing-orders document for a specific engagement (name, scope, current hypothesis)
- Engagement-specific tool configurations or source lists
- Any domain particulars that would constitute PII or operational sensitivity if leaked

This SKILL.md auto-links private overlays by Hermes's skill-discovery mechanism: any
skill file whose name begins with `{{PACKAGE_SLUG}}-` and is present in `HERMES_HOME/skills/`
is available to the agent alongside this one. No further wiring required.

The sanitization gate (`scripts/check_sanitization.py`) enforces this boundary
automatically on every PR that touches `sensitive_prefixes` paths. If you add engagement
particulars to this shared file by mistake, the gate will catch and block the push.
See `sanitize.config.json` for the full configuration and `docs/sanitization.md` for
the promotion flow.
