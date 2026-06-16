# Contributing to {{PACKAGE_NAME}}

> New here? Read [docs/onboarding-contributors.md](docs/onboarding-contributors.md)
> first — the one-sitting tour of the layout and the one rule that matters most.
> This file is the detailed reference.

`{{PACKAGE_NAME}}` is the shared, generic {{DOMAIN}} capability package — plugins,
skills, tools, and the agent's base soul. Operators run private instances on top of
it; those instances keep their own working data and {{DOMAIN_NOUN}} particulars, which
never live here. Anything you commit here ships to every instance that tracks this
package.

## The one rule

**Never commit {{DOMAIN_NOUN}} particulars.** Names of subjects, clients, targets,
document IDs, engagement codenames, datasets, or anything tied to a specific
{{DOMAIN_NOUN}} belong in the operator's private instance — not here. The `.gitignore`
enforces the structural half of this model (`engagements/`, `instance/`, `.overlay/`
are all gitignored). The sanitization gate enforces the other half on every PR.

If a change only needs an API key, **you do not edit this repo** — the operator adds
the key in HSM or their `.env`. That is a runtime concern, not a code change.

## Three ways to add a capability

| You want to…          | Where it goes                                    | How it ships                                     |
|-----------------------|--------------------------------------------------|--------------------------------------------------|
| Add an **API key**    | operator's HSM env or `.env`                     | injected at runtime — **not a code change**      |
| Add a **tool/skill**  | `hermes-plugin/` or `hermes-skill/`              | merged here → instances pull + restart           |
| Add a **system binary** (`{{EXAMPLE_TOOL}}`, …) | `docker/Dockerfile.{{PACKAGE_NAME}}` | image rebuild + redeploy (operator action) |

When in doubt, reach for `hermes-plugin/` over the Dockerfile. An image rebuild
requires a coordinated operator action across all deployed instances; a plugin pull is
just `git pull` + restart.

## Promotion flow

1. Branch from `main`.
2. Make your change. Add tests for new behavior (`python -m pytest tests/ -v`).
   Install dev deps first: `pip install -r requirements-dev.txt`.
3. Open a PR against `main`.
4. Both the `tests` check and the `sanitization` check must pass (or be explicitly
   cleared — see merge policy below).
5. A maintainer reviews and merges. Do not merge your own PR unreviewed.

## Sanitization

Every PR that touches `hermes-skill/`, `hermes-plugin/`, `docker/SOUL*`, `docs/`, or
top-level markdown files is scanned automatically by `scripts/check_sanitization.py`.
The scanner has two layers:

**Layer 1 — deterministic (no deps, fails closed):** regex patterns for credentials
and PII (API keys, private keys, email addresses, phone numbers, non-local IP
addresses). A hit here is a hard stop — the check fails and the PR cannot proceed
until the content is removed.

**Layer 2 — semantic (LLM-backed, advisory):** an LLM prompt, configured in
`sanitize.config.json`, asks whether the diff contains {{DOMAIN_NOUN}} particulars. A
flag is **not** an automatic rejection — it routes the PR to a human maintainer who
makes the call. If your PR is flagged and you believe it's clean, say so in the PR
description; a maintainer reviews the flagged content and decides.

The semantic layer runs when `ANTHROPIC_API_KEY` is set in CI secrets. Without the
key it skips with a warning (and the `--require-semantic` flag turns that skip into a
hard failure, for maintainers who need the full gate in CI).

To tune what counts as a particular for this domain, edit `sanitize.config.json` —
that is the single configuration surface for the gate. See the inline comments in that
file.

## Merge policy (convention-enforced)

These rules are enforced by **convention, not by GitHub branch protection** — GitHub
does not enforce protected branches on private repos under the free plan. See
[docs/privacy-and-visibility.md](docs/privacy-and-visibility.md) for the rationale.
The `tests` and `sanitization` checks run and are visible on every PR, so:

- **Red `tests` = hard stop.** Do not merge until the suite is green.
- **Deterministic SECRET/PII hit = hard stop.** Remove the flagged content; there is
  no override path.
- **Semantic FLAG = human review required.** A maintainer must inspect the flagged
  content and approve before merge. The flag is advisory; the human is the authority.
- **Do not merge your own PR unreviewed.** Wait for a maintainer's explicit approval.

When the project moves to a plan that supports protected branches, or before adding
external contributors, these become hard-enforced gates rather than conventions.

## Adding a capability — worked examples

### API key only

The operator needs to call a new third-party service. No code change is needed here.
The operator adds the key to HSM under the agent's environment config (or to their
`.env` for local development). The tool code that reads the key may already exist, or
it gets added as a plugin (see below) — but the key value itself is never committed.

### New tool/skill

Create the tool in `hermes-plugin/` following the existing plugin conventions, or add
a skill document to `hermes-skill/`. Open a PR. Once merged, operators pull the update
and restart their agent. No image rebuild required.

### New system binary

Add the install step to `docker/Dockerfile.{{PACKAGE_NAME}}`. Document why the binary
is needed and what capability it unlocks. Once merged, operators rebuild the image
(`docker build`) and redeploy — this is a coordinated operator action, so minimize
these changes and batch them when possible.

## Promoting to your own package or upstream HSM

If your work generalizes beyond this package — a plugin pattern that any Hermes agent
could use, a sanitization improvement, a workflow change — see
[docs/promotion-and-upstream.md](docs/promotion-and-upstream.md) for the promotion
flow: how to extract and sanitize work from your private instance into a publishable
form, and how to submit upstream to the HSM base.
