# SETUP.md — Instantiation checklist

Run this once after clicking **"Use this template"**. By the end you will have a
functioning, named agent package with a working sanitization gate and CI secret.
Delete this file when done.

---

## 1. Pick and rename your domain noun

Decide what a single unit of work is called in your domain:
`investigation`, `client`, `engagement`, `campaign`, `case`, `patient`, etc.
This becomes the name of the ignored working-data directory and the semantic
layer's framing noun.

**Rename the directory placeholder in `.gitignore`:**

```bash
# Replace "engagements" everywhere in .gitignore with your noun (plural):
sed -i '' 's/engagements/investigations/g' .gitignore   # macOS
# or on Linux:
# sed -i 's/engagements/investigations/g' .gitignore
```

**Create the real directory with a gitkeep:**

```bash
mkdir investigations
touch investigations/.gitkeep
git add investigations/.gitkeep .gitignore
```

**Update `sanitize.config.json` → `semantic.domain_noun`:**

```json
"domain_noun": "investigation"
```

---

## 2. Fill `sanitize.config.json`

Open `sanitize.config.json` and fill every key that still reads `"your-*"` or
contains a `$comment`.

```jsonc
{
  "package_name": "{{YOUR_PACKAGE_NAME}}",        // e.g. "osint-engine"
  "package_kind": "SHARED, public agent package", // keep unless you know better

  "sensitive_prefixes": [
    "hermes-skill/",
    "hermes-plugin/",
    "docker/SOUL",
    "docs/"
    // add any other prose dirs whose content could leak domain particulars
    // e.g. "templates/", "playbooks/"
  ],

  "semantic": {
    "domain_noun": "{{DOMAIN_NOUN}}",             // set in step 1
    "flag_examples": [
      // concrete examples of what a LEAKED particular looks like in YOUR domain:
      // "subject or client name tied to one active {{DOMAIN_NOUN}}",
      // "codename, handle, or ID used to identify one {{DOMAIN_NOUN}}",
      // "target hostname or URL specific to one {{DOMAIN_NOUN}}"
    ],
    "do_not_flag_examples": [
      // things that are NOT particulars in your domain:
      // "generic methodology steps (how to structure a workflow)",
      // "tool, API, or library names",
      // "well-known public reference material used illustratively"
    ],
    "model": "claude-opus-4-8"
  },

  "deterministic": {
    "enabled": true,
    "allow_substrings": [
      "noreply@anthropic.com",
      "example.com",
      "user@example",
      "127.0.0.1",
      "0.0.0.0"
      // add any known-safe strings that the regex layer would otherwise hit —
      // exact line substrings, e.g. a placeholder email in a README code block
    ]
  }
}
```

The deterministic layer (credentials, PII) needs no tuning — the defaults are
conservative and fail closed. Only `flag_examples`, `do_not_flag_examples`, and
`allow_substrings` are yours to tune.

---

## 3. Add the CI secret

The semantic layer in CI requires an Anthropic API key. Without it the workflow
logs a loud warning and skips the semantic check.

1. Go to **Settings → Secrets and variables → Actions → New repository secret**.
2. Name: `ANTHROPIC_API_KEY`, value: your key.
3. Use a **dedicated, capped key** (a separate key per package is easy to rotate
   and lets you monitor usage per package in the Anthropic console).

If you want CI to hard-fail when the key is missing (e.g. to catch misconfigured
forks), edit `.github/workflows/sanitization.yml` and add `--require-semantic` to
the gate step:

```yaml
run: |
  BASE="origin/${{ github.base_ref }}"
  git diff --name-only "$BASE...HEAD" \
    | xargs -r python scripts/check_sanitization.py --require-semantic
```

---

## 4. Customize the agent surface

These are the three files that define what the agent IS:

| File | What it controls |
|---|---|
| `hermes-plugin/` | Tools the agent can call. Add one `.py` file per tool. |
| `hermes-skill/SKILL.md` | Methodology the agent follows. Domain-specific workflow, grading rubric, output format. |
| `docker/SOUL.template.md` | Standing orders and tier policy. Operator copies this to `docker/SOUL.md` at deploy time. |

Start with `hermes-skill/SKILL.md` — it is the clearest place to express what
makes this package distinct from a blank Hermes agent. Replace every
`{{PLACEHOLDER}}` with your domain-specific content.

Do NOT commit operator-specific configuration (persona names, team names,
deployment targets) into these files. Those belong in `instance/` or the
operator's HSM env.

---

## 5. Add your domain logic

**`engine/`** — the domain processing layer (optional).
If your package needs a pipeline (parsers, normalizers, scorers, a local DB),
put it here. If you only need plugins and a skill, delete this directory:

```bash
rm -rf engine/
```

**`example-collectors/`** — reference adapters for your domain's data sources.
Replace the placeholder examples with minimal, working adapters that illustrate
the integration pattern. These are teaching artifacts, not production code —
strip any hardcoded endpoints or credentials before committing.

---

## 6. Decide visibility before first push

The repository should stay **private** until you have run the full gate (step 7)
and deliberately decided to open it.

Read `docs/privacy-and-visibility.md` before flipping to public. The short version:

- `{{DOMAIN_NOUN}}` working data lives in `{{DOMAIN_NOUN_PLURAL}}/` (gitignored).
- Operator overlays live in `instance/` and `.overlay/` (gitignored).
- The sanitization gate guards prose and agent-surface files; it does not replace
  judgment — if you are unsure whether a file is clean, keep it private or in a
  separate private repo.
- The recommended pattern for sensitive collateral is separate private repos that
  pull this package as a dependency, not subdirectories here.

---

## 7. Verify the gate locally

Install the test dep and run the deterministic layer offline (no API key needed):

```bash
pip install anthropic           # for the semantic layer
pip install pytest              # if not already installed

# Run the scanner self-tests (deterministic, no key needed):
python -m pytest tests/ -q

# Full-tree audit, deterministic only (no key):
python scripts/check_sanitization.py --full-tree

# Full-tree audit with the semantic layer:
export ANTHROPIC_API_KEY=sk-ant-...
python scripts/check_sanitization.py --full-tree
```

Expected output when clean:

```
ok      hermes-skill/SKILL.md
ok      hermes-plugin/your_tool.py
...
sanitization: clean.
```

A `SECRET/PII` line is a hard fail — remove the content before any commit.
A `FLAGGED` line routes to human review — read the reason and decide.

---

## 8. Delete this file

Once the package is named, gated, and the agent surface has real content:

```bash
git rm SETUP.md
git commit -m "instantiate: {{YOUR_PACKAGE_NAME}}"
```

Done.
