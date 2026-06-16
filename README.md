# {{PACKAGE_NAME}}

A template for building a sanitized, use-case-customised Hermes agent package — runnable standalone or managed via HSM (Hermes Swarm Map).

## Multiplayer by design

This template targets [**hermes-agent-mt**](https://github.com/NimbleCoAI/hermes-agent-mt) —
the multi-tenant Hermes runtime — not a single-user harness. One deployment can serve many
users and contexts (Signal DMs, group chats, tenants) at once, which is the whole reason the
privacy model has two levels rather than one: what your *repository* shows the world, and what
one *user* of a running deployment can see of another. The instance overlay, the sanitization
gate, and the glocal cross-context read floor are all here because multiplayer is the default,
not an afterthought. If you only ever run one user against one agent, this still works — you
just won't need half of it. See [docs/privacy-and-visibility.md](docs/privacy-and-visibility.md).

The package layer itself is runtime-agnostic (a plugin + a skill + a soul + optional engine),
but the scaffolding — base image, instance bootstrap, HSM consumption — assumes the
`hermes-agent-mt` image as its base. Point `{{BASE_HERMES_IMAGE}}` at it in
[docs/onboarding.md](docs/onboarding.md).

---

## Use this template

Click **"Use this template"** on GitHub to create your private repo, then follow the instantiation checklist in [SETUP.md](SETUP.md).

The checklist covers: renaming placeholders, filling `sanitize.config.json`, wiring `ANTHROPIC_API_KEY` in CI, and verifying the gate runs clean before your first real commit.

---

## What you get

- **Two-layer sanitization gate** — deterministic regex (secrets, PII, API keys) as a hard-fail floor; LLM-semantic scan for domain particulars as an advisory layer routed to human review. Both run on every PR diff.
- **Instance-overlay `.gitignore`** — `engagements/` (rename per domain), `instance/`, `.overlay/`, `.env` are private by construction. Operational data cannot accidentally reach the shared package.
- **`hermes-plugin/` scaffold** — a working `register()` skeleton with placeholder tools; drop in your domain logic.
- **`hermes-skill/SKILL.md` baseline** — methodology stub for the agent; fill in your domain's reasoning patterns and source-evaluation criteria.
- **Hot-mount docker setup** — `docker/Dockerfile.{{SLUG}}` + `docker/SOUL.{{SLUG}}.md`; rebuild only when system deps change, mount plugin live.
- **Contributor and promotion docs** — `CONTRIBUTING.md` explains the three ways to add a capability; `docs/promotion-and-upstream.md` explains when and how a private instance contributes back to the shared package.
- **CI workflow** — `.github/workflows/sanitization.yml` runs scanner self-tests and the diff-mode gate on every PR.

---

## The model

```
fork → develop privately under operational pressure
     → generalize + sanitize
     → contribute through the gate
```

You build under real conditions in your private instance. When a capability proves itself generic, you strip the particulars, run the gate, and open a PR. The gate catches what you missed. A maintainer makes the final call. That loop — not upfront design — is how the shared package stays both useful and clean.

---

## Layout

| Path | What it's for | Customize? |
|------|---------------|-----------|
| `engine/` | Your domain logic: data model, scoring, dedup, audit | Yes — this is your core |
| `example-collectors/` | Example data-source integrations; copy and adapt | Yes — add real collectors here |
| `hermes-plugin/` | Plugin `register()` + tool definitions for the agent | Yes — expose your engine as agent tools |
| `hermes-skill/SKILL.md` | Agent methodology: how to reason, grade sources, iterate | Yes — define your domain's patterns |
| `docker/SOUL.{{SLUG}}.md` | Agent identity / soul for your domain | Yes — set role, defaults, tone |
| `docker/Dockerfile.{{SLUG}}` | System-level deps (binaries, libraries) for the agent image | Only if you need system deps |
| `engagements/` | Per-engagement working data — gitignored, stays local | N/A — ignored by construction |
| `instance/` `.overlay/` | Operator-local overrides, instance-specific config | N/A — ignored by construction |
| `scripts/check_sanitization.py` | The sanitization gate — runs in CI and via gardener | No — leave alone |
| `.github/workflows/sanitization.yml` | CI gate | No — leave alone |
| `.gitignore` | Instance-overlay privacy model | No — leave alone |
| `sanitize.config.json` | **The one tuning surface** — teach the gate your domain | Yes — required on setup |

---

## Two ways to run

**Standalone** — clone the repo, mount `hermes-plugin/` into an existing Hermes instance, and start the agent. See [docs/onboarding.md](docs/onboarding.md).

**HSM-managed** — register the package in HSM, which handles image builds, env injection, and lifecycle. See [docs/onboarding.md](docs/onboarding.md#hsm).

---

## Privacy

Operational data is private by construction (`.gitignore`) and by automated scan (sanitization gate). See [docs/privacy-and-visibility.md](docs/privacy-and-visibility.md).

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the three ways to add a capability and the sanitization workflow.

When a capability is ready to promote from your private instance back to this shared package, see [docs/promotion-and-upstream.md](docs/promotion-and-upstream.md).
