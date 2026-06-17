"""Two-layer sanitization gate for a use-case agent package.

Layer 1 (deterministic): scans changed text for credentials / PII — API keys,
private keys, tokens, emails, phones, IPs. NO external dependencies. FAILS CLOSED.
Always runs, even offline / without an API key.

Layer 2 (semantic): sends content-bearing files (skills, souls, docs, prose) to
an LLM that flags operator/engagement *particulars* — names, case IDs, hostnames,
anything that would make a "generic" artifact actually specific to one operator.
Requires ANTHROPIC_API_KEY; skipped with a loud warning if unset (so local runs
work), REQUIRED in CI (pass --require-semantic to fail when the key is missing).

A flag routes to a human maintainer — it is advisory, not an automatic final
rejection. But the deterministic layer's hits (real secrets/PII) are hard fails.

Modes:
  check_sanitization.py a.md b.py        # explicit file list (CI diff mode)
  check_sanitization.py --full-tree      # every git-tracked file (gardener/audit)
  check_sanitization.py --all            # alias for --full-tree

Config: sanitize.config.json at repo root (see that file's comments).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------- config

def load_config(root="."):
    path = os.path.join(root, "sanitize.config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        # Sensible defaults so the gate still runs on a fresh template.
        return {
            "package_kind": "SHARED, public agent package",
            "sensitive_prefixes": ["hermes-skill/", "hermes-plugin/", "docker/SOUL", "docs/"],
            "semantic": {"domain_noun": "operational engagement", "flag_examples": [],
                         "do_not_flag_examples": [], "model": "claude-opus-4-8"},
            "deterministic": {"enabled": True, "allow_substrings": []},
        }

# ---------------------------------------------------------------- layer 1: deterministic

# Conservative, low-false-positive credential/PII patterns. Each is (label, regex).
_DETERMINISTIC_PATTERNS = [
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("notion-token", re.compile(r"\bntn_[A-Za-z0-9]{20,}")),
    ("private-key-block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("us-phone", re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)")),
    # E.164 international (e.g. a contact wired into config/SOUL): "+" + 7–15 digits,
    # no separators. The us-phone pattern only covers North-American formatting.
    ("intl-phone", re.compile(r"(?<!\d)\+\d{7,15}(?!\d)")),
    ("ipv4", re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)")),
]


def scan_deterministic(content, allow_substrings):
    """Return a list of (label, matched_text) for credential/PII hits, minus
    any line containing an allowlisted substring."""
    hits = []
    for label, pat in _DETERMINISTIC_PATTERNS:
        for m in pat.finditer(content):
            line_start = content.rfind("\n", 0, m.start()) + 1
            line_end = content.find("\n", m.end())
            line = content[line_start: line_end if line_end != -1 else len(content)]
            if any(allow in line for allow in allow_substrings):
                continue
            hits.append((label, m.group(0)))
    return hits

# ---------------------------------------------------------------- layer 2: semantic

def build_system_prompt(cfg):
    sem = cfg.get("semantic", {})
    kind = cfg.get("package_kind", "SHARED, public agent package")
    noun = sem.get("domain_noun", "operational engagement")
    flag = "\n".join(f"- {x};" for x in sem.get("flag_examples", [])) or \
        f"- any particular tied to one specific {noun};"
    keep = "\n".join(f"- {x};" for x in sem.get("do_not_flag_examples", [])) or \
        "- generic methodology, tool/API names, well-known public reference material;"
    return (
        f"You review proposed content for a {kind}. It must contain only generic "
        f"methodology and tooling. It must NOT contain particulars of any specific "
        f"{noun}.\n\nFlag the content if it contains any of:\n{flag}\n\n"
        f"Do NOT flag:\n{keep}\nWhen uncertain whether something is a particular vs. "
        f"generic, lean toward flagging so a human can decide.\n\nRespond with ONLY a "
        f'JSON object: {{"flagged": <bool>, "reasons": [<short strings>]}}.'
    )


def _extract_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object in model reply: {text!r}")
    try:
        return json.loads(text[start: end + 1])
    except json.JSONDecodeError:
        start2 = text.rfind("{")
        if start2 != -1 and start2 < end:
            return json.loads(text[start2: end + 1])
        raise


def assess(content, client, filename, system_prompt, model):
    msg = client.messages.create(
        model=model, max_tokens=1024, system=system_prompt,
        messages=[{"role": "user", "content": f"File: {filename}\n\n---\n{content}\n---"}],
    )
    verdict = _extract_json(msg.content[0].text)
    if "flagged" not in verdict:
        raise ValueError(f"model response missing 'flagged' key: {verdict!r}")
    reasons = verdict.get("reasons", [])
    if isinstance(reasons, str):
        reasons = [reasons]
    return {"flagged": bool(verdict["flagged"]), "reasons": list(reasons)}


def _make_client():  # pragma: no cover - thin wrapper, mocked in tests
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# ---------------------------------------------------------------- file selection

def select_sensitive_files(paths, prefixes):
    """Content-bearing files for the SEMANTIC layer: anything under a sensitive
    prefix, plus top-level prose .md (README, CONTRIBUTING)."""
    out = []
    for p in paths:
        if p.startswith(tuple(prefixes)):
            out.append(p)
        elif p.endswith(".md") and "/" not in p:
            out.append(p)
    return out


def git_tracked_files(root="."):
    """All git-tracked files, for --full-tree mode."""
    res = subprocess.run(["git", "-C", root, "ls-files"],
                         capture_output=True, text=True, check=True)
    return [ln for ln in res.stdout.splitlines() if ln.strip()]

# ---------------------------------------------------------------- main

def main(argv, root=".", client_factory=_make_client):
    args = list(argv)
    require_semantic = "--require-semantic" in args
    args = [a for a in args if a != "--require-semantic"]

    cfg = load_config(root)
    prefixes = cfg.get("sensitive_prefixes", [])
    det_cfg = cfg.get("deterministic", {})
    allow = det_cfg.get("allow_substrings", [])

    if args and args[0] in ("--full-tree", "--all"):
        candidates = git_tracked_files(root)
    elif args:
        candidates = args
    else:
        print("sanitization: no files given (use a file list or --full-tree).")
        return 0

    # ---- Layer 1: deterministic, over ALL candidate text files (fails closed)
    det_hits = {}
    skip_paths = tuple(det_cfg.get("skip_paths", []))
    if det_cfg.get("enabled", True):
        for rel in candidates:
            if skip_paths and rel.startswith(skip_paths):
                continue  # e.g. tests/ — legitimately holds credential-shaped fixtures
            path = os.path.join(root, rel)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, encoding="utf-8") as fh:
                    content = fh.read()
            except (UnicodeDecodeError, OSError):
                continue  # binary / unreadable — skip
            hits = scan_deterministic(content, allow)
            if hits:
                det_hits[rel] = hits

    # ---- Layer 2: semantic, over content-bearing files only
    sensitive = select_sensitive_files(candidates, prefixes)
    sem_flagged = {}
    sem_ran = False
    if sensitive:
        if os.environ.get("ANTHROPIC_API_KEY"):
            sem_ran = True
            client = client_factory()
            system_prompt = build_system_prompt(cfg)
            model = cfg.get("semantic", {}).get("model", "claude-opus-4-8")
            for rel in sensitive:
                path = os.path.join(root, rel)
                if not os.path.exists(path):
                    continue
                with open(path, encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                verdict = assess(content, client, rel, system_prompt, model)
                if verdict["flagged"]:
                    sem_flagged[rel] = verdict["reasons"]
        elif require_semantic:
            print("ERROR: --require-semantic set but ANTHROPIC_API_KEY is missing.")
            return 2
        else:
            print("WARNING: ANTHROPIC_API_KEY unset — semantic layer SKIPPED "
                  "(deterministic layer still ran). Set the key for full coverage.")

    # ---- report
    for rel, hits in det_hits.items():
        print(f"SECRET/PII {rel}:")
        for label, text in hits:
            shown = text if len(text) < 12 else text[:6] + "…"
            print(f"  - {label}: {shown}")
    for rel, reasons in sem_flagged.items():
        print(f"FLAGGED {rel}:")
        for r in reasons:
            print(f"  - {r}")
    clean = [r for r in sensitive if r not in sem_flagged and r not in det_hits]
    for rel in clean:
        print(f"ok      {rel}")

    if det_hits:
        print("\nsanitization: credentials/PII detected — HARD FAIL (remove before merge).")
        return 1
    if sem_flagged:
        print("\nsanitization: possible particulars found — needs human review.")
        return 1
    tail = "" if sem_ran else " (semantic layer skipped — deterministic only)"
    print(f"\nsanitization: clean{tail}.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
