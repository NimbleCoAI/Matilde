# Onboarding: Running & Contributing to {{PACKAGE_NAME}}

Welcome. This is the one-sitting tour of how `{{PACKAGE_NAME}}` is structured,
how to get it running, how to keep it current, and the one rule you need to
internalize before you commit anything.

Jump to: [How it fits together](#how-it-fits-together-read-this-first) ·
[Run standalone](#a-run-it-standalone) · [Run through HSM](#b-run-it-through-hsm) ·
[Update safely](#c-update-the-running-agent) ·
[Pull updates without overwriting your work](#d-pull-updates-without-overwriting-your-work) ·
[Contribute without leaking](#e-contribute-without-leaking)

---

## How it fits together (read this first)

The one thing that trips people up: **the image and your data are entirely separate.**
The image carries the runtime and any system-level dependencies. Your code, skills,
soul, and engagement data live in a directory you own — the agent's home — which is
bind-mounted into the container at `/opt/data` (`HERMES_HOME`).

```
   ┌──────────────────────────────┐         ┌───────────────────────────────────────┐
   │  THE IMAGE                    │  mounts │  YOUR DATA DIR  (HERMES_HOME)         │
   │  {{IMAGE}}                    │   ───▶  │  = /opt/data — a directory you own    │
   │                               │         │                                       │
   │  • Hermes runtime             │         │  • {{PACKAGE_NAME}}/  ← git clone of  │
   │  • System dependencies /      │         │      THIS repo (engine/, plugin,      │
   │    domain-specific binaries   │         │      collectors/, skill, docs)        │
   │    ({{DOMAIN_BINARIES}})      │         │                                       │
   │                               │         │  • skills/       ← operator skills   │
   │  NOTHING ELSE.                │         │  • SOUL.md       ← operator soul     │
   │  No plugin, no skill,         │         │  • config.yaml   ← plugins on/off    │
   │  no soul, no engagements.     │         │  • engagements/  ← private work data │
   └──────────────────────────────┘         └───────────────────────────────────────┘
```

Concretely:

- **The image ships no {{DOMAIN_NOUN}} capability at all.** The plugin, collectors,
  skill text, and soul are code you get by cloning this repo into your data dir. They
  load at runtime via `PYTHONPATH=/opt/data/{{PACKAGE_NAME}}`. When the shared code
  changes, you `git pull` it — you never rebuild the image.
- **The image is only rebuilt when a system-level binary changes** — a new tool that
  has to be installed at the OS layer. Most capability changes do not touch the image.
- **`engagements/`** (git-ignored) holds all your private work. Rename it to match
  your domain (investigations/, clients/, campaigns/, etc.) — `.gitignore` already
  covers the pattern.

The one-time wiring — clone the code, seed the soul, link the skill, enable the plugin —
is done by `docker/instance-setup.sh`, which is idempotent and never overwrites
content you've already customized.

---

## A. Run it standalone

You need: Docker, a data directory you control, and the package image.

> **Base runtime.** `{{BASE_HERMES_IMAGE}}` should point at
> [`hermes-agent-mt`](https://github.com/NimbleCoAI/hermes-agent-mt) — the multi-tenant
> Hermes runtime this template is built for. It carries the per-context scoping (the
> glocal read floor, `MemoryStore(context_id=)`) that makes one deployment safe to share
> across users. You *can* base on a single-user Hermes image, but then the cross-user
> guarantees in [privacy-and-visibility.md](privacy-and-visibility.md) Level 2 don't apply.

**1. Build the image** (once; again only when `docker/Dockerfile` changes a system
binary):

```bash
git clone https://github.com/{{GITHUB_ORG}}/{{PACKAGE_NAME}}.git
cd {{PACKAGE_NAME}}
docker build -f docker/Dockerfile -t {{IMAGE}}:local \
  --build-arg BASE_IMAGE={{BASE_HERMES_IMAGE}} .
```

**2. Wire up your data dir** (clones the package, seeds the soul, links the skill,
enables the plugin):

```bash
HERMES_HOME=/path/to/your/datadir bash docker/instance-setup.sh
```

This is idempotent. Run it again after a fresh clone — it will not clobber anything
you have already customized.

**3. Run** — a minimal compose:

```yaml
services:
  {{PACKAGE_NAME}}:
    image: {{IMAGE}}:local
    volumes:
      - /path/to/your/datadir:/opt/data
    env_file:
      - /path/to/your/datadir/.env
    environment:
      - HOME=/opt/data
      - PYTHONPATH=/opt/data/{{PACKAGE_NAME}}
    command: gateway
```

```bash
docker compose up -d
```

The plugin must appear in `config.yaml` under `plugins.enabled`. The setup script
tells you if it is missing.

**What's in `.env`** — your API keys for any external services this package uses. The
`.env` file is git-ignored; never commit it. The list of required keys is in
`docker/instance-setup.sh` and in the `requires_env` block of
`hermes-plugin/plugin.yaml`. See `.env.example` for the full set with descriptions.

---

## B. Run it through HSM

HSM (Hermes Swarm Map) is the harness manager used in production deployments. It
owns the compose lifecycle, environment/secret injection, and per-agent deploy
operations. When HSM manages your agent, **do not use `docker compose` directly** —
use the HSM API. Running compose by hand against an HSM-managed agent can produce
conflicting state.

The data layout is identical to standalone. What changes is the orchestrator:

- **Enable the plugin** via the HSM UI or API. HSM reads `hermes-plugin/plugin.yaml`
  and surfaces the capability toggle.
- **Environment / API keys** go into the HSM env store (encrypted). They are injected
  at container start. The `requires_env` keys declared in `plugin.yaml` are what HSM
  looks for — add any missing keys there and restart.
- **Restart / redeploy** via the HSM API. The three restart modes:
  - `quick` — restart the container, no compose changes (e.g. after a `git pull`)
  - `recreate` — recreate from compose (e.g. after changing an image pin)
  - `rebuild` — rebuild the image (only when `docker/Dockerfile` has changed)
- **The data dir** is still a bind-mount; HSM configures the mount path. Your
  `engagements/` and `instance/` overlays are untouched by deploy operations.

In short: standalone is for local development; HSM is how production instances run.
The underlying model is the same — the orchestrator differs.

---

## C. Update the running agent

There are two update paths. Know which your change is before you act:

| Your change is…                                    | How it ships                                    | Rebuild? |
|----------------------------------------------------|-------------------------------------------------|----------|
| **Code** — a tool, plugin, skill, or soul update   | `git pull` in the data dir, then **restart**    | No       |
| **System binary** — a new OS-level dependency      | rebuild `docker/Dockerfile`, bump the image pin, **recreate** | Yes  |
| **An API key**                                     | add it in HSM env (or `.env` for standalone)    | No       |

The common case — a new tool, an updated skill, a soul edit — ships with a pull and
a restart, no image rebuild:

```bash
# 1. PR merged to main
# 2. on the running instance:
cd /opt/data/{{PACKAGE_NAME}} && git pull
# 3. restart via HSM quick-restart, or `docker compose restart` if standalone
```

Because code is hot-mounted at runtime, nothing has to be baked into the image for
code changes to take effect. Image rebuilds are rare and explicit.

---

## D. Pull updates without overwriting your work

The whole layout is built around this property: **your private material lives
outside the tracked repo, so `git pull` fast-forwards the shared code and never
touches your data.**

Where your private material lives:

- **`engagements/`** (or whatever you renamed it to) — git-ignored. Work data,
  datasets, notes. Cannot be committed even by accident.
- **`instance/` and `.overlay/`** — git-ignored. Instance-specific skills, soul
  customizations, local config.
- **Your data dir** (`HERMES_HOME`) — `SOUL.md`, your `skills/`, memory, `config.yaml`.
  None of it is tracked in this repo at all.

So updating is always:

```bash
cd /opt/data/{{PACKAGE_NAME}} && git pull   # clean fast-forward, every time
```

**The discipline that keeps it clean:** do not edit a tracked, shared file for
instance-specific content. If you want engagement-specific skill text, add it as a
separate skill under your `skills/` overlay — do not edit `hermes-skill/SKILL.md`
in place. An edited tracked file produces a merge conflict on the next pull; an
overlay file is never in the way. Particulars in `HERMES_HOME`, shared capability
via pull.

---

## E. Contribute without leaking

When you build something under operational pressure that would be useful to everyone
in this package, contribute the generic version: strip the engagement particulars,
keep the method, open a PR. That act of generalization is the contribution boundary.

The workflow:

```
branch from main → PR → CI (tests + sanitization gate) → maintainer review → merge → instances pull
```

Two checks must pass:

1. **`tests`** — `python -m pytest tests/ -v`. Add tests for new behavior; a red
   test is a hard stop.
2. **`sanitization`** — `scripts/check_sanitization.py` scans the diff. It runs a
   deterministic layer (credentials, PII) that fails closed, then a semantic layer
   (configured in `sanitize.config.json`) that flags {{DOMAIN_NOUN}}-specific
   particulars for human review. A flag is not an automatic rejection; a maintainer
   decides. If you believe a flag is a false positive, say so in the PR.

Three layers protect you from leaking:

1. **Structural** — particulars live in `engagements/` (git-ignored) and
   `HERMES_HOME` (not tracked). You cannot commit what isn't in the tree.
2. **The gate** — every PR touching skills, soul, docs, or plugin code is scanned.
   A flag routes to a human before merge.
3. **The discipline** — when a technique built for one engagement is reusable,
   generalize it (method stays, particulars go) and PR that. The gate proves
   nothing leaked; the promotion is how the shared package gets better without
   anyone's private work becoming visible.

Full details on both sides of the contribution flow — what to add, where it goes,
and how to handle a flag — are in [CONTRIBUTING.md](../CONTRIBUTING.md) and
[docs/promotion-and-upstream.md](promotion-and-upstream.md).

---

## The one rule

> **Never commit {{DOMAIN_NOUN}} particulars to this repo.** No subject or client names,
> engagement identifiers, document IDs, dataset filenames, account handles, or case
> details. They live in your private overlay (`engagements/`, `instance/`, your data
> dir) — never here.

## What you have and don't have

| You have…                                      | You do **not** have…                           |
|------------------------------------------------|------------------------------------------------|
| Read/write access to `{{PACKAGE_NAME}}`        | Access to anyone else's instance or data       |
| Ability to open and review PRs                 | HSM / server / production deploy access        |
| Your own `HERMES_HOME` (yours alone)           | Production secrets or API keys                 |

Welcome. Build generic capability here; keep your {{DOMAIN_NOUN}} data yours.
