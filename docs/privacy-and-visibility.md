# Privacy and Visibility

Two different questions get conflated under "privacy," and this package treats
them as separate problems with separate machinery:

1. **Repository visibility** — who can see the package *source*. Governed by
   GitHub repo settings, the `.gitignore` instance overlay, and the
   sanitization gate.
2. **Cross-user visibility inside a running harness** — what one user, chat,
   or tenant of a shared deployment can see about *another's* context.
   Governed by the glocal scoping model in `hermes-agent-mt` + HSM.

Getting Level 1 right does nothing for Level 2, and vice versa. Read both
before you deploy {{PACKAGE_NAME}} for more than one person.

---

## Level 1 — Repository visibility

### Private by default

The package repo starts private and stays private until you decide otherwise.
This is a deliberate posture, not an oversight: in an ecosystem where anyone
can fork and an agent can reimplement a published capability in an afternoon,
**lead time is the only durable moat**. You develop under operational
pressure in private; you publish when the generalized form is worth more to
you as a commons contribution than as an edge.

Publishing is a choice you make per artifact, not a default you drift into.

### Per-artifact repos and flip-to-public

Don't build a monorepo you can only publish all-or-nothing. Each shareable
artifact — a skill, a plugin — can live in its own small private repo and be
consumed by reference:

```
git:{{GITHUB_ORG}}/{{ARTIFACT_REPO}}#v1.2.0
```

HSM installs artifacts from git sources pinned to a tag. "Going public" for
one artifact is then a single operation: flip that repo's visibility in
GitHub settings. It's instant, it keeps the full history, and it doesn't drag
the rest of your private work with it. Run the sanitization scanner over the
repo's full tree **before** the flip:

```bash
git ls-files | xargs python scripts/check_sanitization.py
# or: python scripts/check_sanitization.py --full-tree
```

History note: flipping visibility publishes the repo's *entire history*. If
early commits predate your sanitization discipline, audit them or publish
from a fresh repo seeded with the current tree.

### The inbound trust gate

Visibility cuts both ways: once there's a commons, you'll also *consume*
artifacts other teams published. The reason that's safe is the gate on the
install side, not trust in the author. When HSM installs an artifact from a
git source, it:

1. **Enforces the pin** — fetches exactly the declared `#<tag>`; the artifact
   can't silently change under you after review.
2. **Runs a threat-pattern scan** over the artifact body (injection patterns,
   credential exfil shapes) before it reaches any agent.
3. **Optionally checks a declared-capabilities allow-list** — the artifact
   declares what it needs; the deployment decides what it gets.

That is the inbound boundary. Your sanitization gate protects *others* from
your particulars; the trust gate protects *you* from others' artifacts. A
commons needs both directions.

### Branch protection: an honest caveat

GitHub does **not** enforce required reviews or required status checks on
private repos under the free plan. So while the `sanitization` and `tests`
checks run and are visible on every PR, nothing mechanically stops a merge
past a red check. Your options:

- **Convention-enforced merge policy** (the default for a small private
  team): red check = hard stop, flagged sanitization = human review before
  merge, no self-merging unreviewed PRs. Spelled out in
  [CONTRIBUTING.md](../CONTRIBUTING.md) — adopt it verbatim or tighten it.
- **GitHub Team plan** (or making the repo public): branch protection becomes
  hard-enforced. Do this before you add contributors you haven't worked with.

Don't pretend convention is enforcement. It works at 2–4 trusted people and
degrades from there.

### Structural privacy: the instance overlay

The sanitization gate is only half of Level 1. The other half is structural:
the `.gitignore` instance overlay makes {{DOMAIN_NOUN}} data private **by
construction** — it cannot be committed, so it cannot leak through a PR:

```
{{ENGAGEMENTS_DIR}}/*     # per-{{DOMAIN_NOUN}} working data (rename to your domain)
instance/                 # operator-specific skills, souls, config
.overlay/                 # local overrides
.env, .env.*              # keys and secrets
*.pem, *_rsa, *.key
```

Division of labor:

| Layer | Protects against | Mechanism |
|---|---|---|
| Instance overlay (`.gitignore`) | committing engagement data at all | structural — git never sees it |
| Deterministic scanner (Layer 1) | secrets/PII that land in tracked files anyway | regex, no deps, **fails closed** |
| Semantic scanner (Layer 2) | use-case particulars in prose/skills/souls | LLM flag → human review |

Keep live work under the overlay and the gate rarely has anything to catch.
The gate exists for the cases where discipline slips — a subject name pasted
into a skill, a client identifier in a docstring.

---

## Level 2 — Cross-user visibility inside a running harness

This level only matters if your deployment serves **more than one context** —
multiple Signal/Telegram groups, multiple DM users, multiple tenants — from
one agent. If you run strictly solo, skim the read-floor section and move on.

### The problem

A single Hermes agent process serves many contexts. Without scoping, its
capabilities are global to the process, and context leaks across chats:

- **Skills** load into one process-wide registry and are injected into the
  system prompt uniformly across every chat.
- **The working filesystem** is one directory per process. A dataset
  downloaded while serving group A sits there, reachable while serving
  group B.
- **Structured memory** is the exception — see below.
- **SOUL** is global per agent by design (one identity).

For a {{DOMAIN_NOUN}}-oriented package this is concrete: two
{{DOMAIN_NOUN}}s served by one agent must not see each other's subjects,
files, or notes.

### The model: a scope ladder

The glocal scoping design (hermes-agent-mt + HSM) is one primitive — **a
scope ladder + role-within-scope + a gated promotion edge + a read floor** —
governing four resource types: skills, structured memory, working
filesystem, SOUL.

```
  global scope        ── deployment-admin owned ──▶ reads inherit DOWN
     ▲                                              writes need role-in-scope
     │  PROMOTION (sanitize → admin-approve)
     │
  context scope       ── members author here ────▶ confined: recurse DOWN, never UP
  (context_id =
   platform:chat_id)

  ════ READ FLOOR (every scope, even admin) ════
  secret-bearing paths are never readable by file tools
```

- Reads inherit down: a context sees `global ∪ its own context`.
- Writes gate by role: members write context-local; only the deployment
  admin writes global.
- Promotion (sanitize → admin approval) is the only context→global edge —
  the same shape as this package's contribute-back gate, one level down.

### What's already scoped: structured memory

`MEMORY.md`/`USER.md` are **already context-scoped** in `hermes-agent-mt` via
`MemoryStore(context_id=…)`: each context reads `contexts/{id}/MEMORY.md`
merged over the global file, path-traversal-sanitized and tested
(`HERMES_MEMORY_SCOPE=channel` is the default). Memory written while serving
one chat does not surface in another.

So the real exposure surface in a multi-context deployment today is **skills
and the working filesystem**, not memory. Plan accordingly.

### The read floor: three layers, stated honestly

The floor stops the "agent reads a secret and launders it into a softer
store" class. It is three layers, and **only the third is an actual security
boundary** — the code itself says so (`file_safety.py`: "This is NOT a
security boundary… the agent can still `cat auth.json`"):

| Layer | Where | What it is | Stops a terminal `cat` of a secret? |
|---|---|---|---|
| **L1** — in-process read-deny on secret paths (`.env`, credential stores, service-account JSON, `*.pem`, …) | image | defense-in-depth | No — the terminal tool bypasses file-tool guards |
| **L2** — terminal command guard: secret-read commands (`cat`/`cp`/`base64` of credential paths) route through the approval flow | image | defense-in-depth + approval | At the command layer, via human approval |
| **L3** — secret not in the agent's mount at all (HSM compose / secret provisioning) | HSM | **the real boundary** | Yes — you can't read what isn't there |

An in-process deny is bypassable by anything running as the same OS user.
L1/L2 raise the cost and create an approval checkpoint; L3 is the only layer
that *removes the capability*. Don't describe L1/L2 as isolation in your own
docs.

### Phase status (as of 2026-06)

Be clear with your team about what's live versus designed:

| Piece | Status |
|---|---|
| Context-scoped structured memory (`MemoryStore(context_id=)`) | **Shipped** in hermes-agent-mt |
| Read floor L1 + L2 (Phase 0) | **Shipped** in the hermes-agent-mt image |
| L3 — secrets out of the agent mount (Phase 0b) | Designed / in progress |
| Per-context skills + working-fs confinement (Phase 1) | Designed / in progress |
| HSM policy plane — roles, promotion workflow (Phase 2) | Designed / in progress |

Until Phase 1 lands, skills and working files are shared across contexts on
a single deployment. If that's unacceptable for your domain (it usually is
for anything client- or subject-sensitive), run one deployment per context.

### Practical guidance for instantiators

If you run multi-tenant — multiple users or contexts on one deployment:

- **Keep per-{{DOMAIN_NOUN}} data under the ignored overlay**
  (`{{ENGAGEMENTS_DIR}}/`, `instance/`). It stays off the shared repo *and*
  gives you one obvious root to confine per-context once Phase 1 lands.
- **Rely on `context_id` memory scoping** — it works today. Don't build a
  parallel memory mechanism that bypasses it.
- **Don't mount shared secrets into the agent namespace.** Anything mounted
  readable is one approval (L2) or one guard gap away from agent-readable.
  Inject per-context credentials at the narrowest scope your setup allows;
  this is L3 thinking applied now, by hand.
- **Don't put {{DOMAIN_NOUN}} particulars in skills.** Skills are currently
  process-global *and* they're package-shaped — particulars in a skill leak
  both across contexts (Level 2) and toward the shared repo (Level 1).

---

## Deciding your posture

| | **Solo-private** | **Team-private** | **Public-commons** |
|---|---|---|---|
| **Repo visibility** | Private, single repo is fine | Private; split shareable artifacts into per-artifact repos early | Public (flipped per artifact, full-tree scan first) |
| **Sanitization gate** | Run it anyway — it's free discipline and keeps history publishable | Required on every PR; merge policy convention-enforced or Team-plan-enforced | Required + `--require-semantic` in CI; switch workflow trigger per the fork-security note in `sanitization.yml` |
| **Cross-user scoping** | Not applicable; still honor the read floor (don't mount secrets you don't need) | Matters if one deployment serves multiple chats/users: overlay + `context_id` memory scoping today, one-deployment-per-context if skills/files must not be shared | Same as team-private for your own deployment; plus the inbound trust gate protects you from artifacts you consume |
| **What you're optimizing** | Speed | Lead time + internal trust | Commons value; your particulars never ship, your methodology does |

Start solo-private. Move right only when the value of sharing exceeds the
value of the lead time you give up — and let the gate, not vigilance, be
what makes that move safe.
