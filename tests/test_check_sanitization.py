"""Tests for the two-layer sanitization gate."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_sanitization as cs  # noqa: E402


# ---- Layer 1: deterministic --------------------------------------------------

def test_detects_anthropic_key():
    hits = cs.scan_deterministic("token = sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAAAA", [])
    assert any(label == "anthropic-key" for label, _ in hits)


def test_detects_private_key_block():
    hits = cs.scan_deterministic("-----BEGIN OPENSSH PRIVATE KEY-----", [])
    assert any(label == "private-key-block" for label, _ in hits)


def test_detects_real_email_but_allows_allowlisted():
    hits = cs.scan_deterministic("contact jane.doe@realcorp.io now", [])
    assert any(label == "email" for label, _ in hits)
    allowed = cs.scan_deterministic("from noreply@anthropic.com header", ["noreply@anthropic.com"])
    assert not any(label == "email" for label, _ in allowed)


def test_detects_ipv4_but_allows_loopback():
    assert any(l == "ipv4" for l, _ in cs.scan_deterministic("host 203.0.113.45", []))
    assert not any(l == "ipv4" for l, _ in cs.scan_deterministic("bind 127.0.0.1", ["127.0.0.1"]))


def test_generic_methodology_is_clean():
    assert cs.scan_deterministic("Structure a handoff: decisions, threads, next step.", []) == []


# ---- file selection ----------------------------------------------------------

def test_select_sensitive_files_prefixes_and_toplevel_md():
    paths = ["hermes-skill/SKILL.md", "engine/db.py", "README.md", "docs/guide.md", "src/x.py"]
    got = cs.select_sensitive_files(paths, ["hermes-skill/", "docs/"])
    assert set(got) == {"hermes-skill/SKILL.md", "README.md", "docs/guide.md"}


# ---- semantic prompt build ---------------------------------------------------

def test_build_system_prompt_uses_config_domain():
    cfg = {"package_kind": "X", "semantic": {"domain_noun": "patient case",
           "flag_examples": ["patient names"], "do_not_flag_examples": ["clinical methodology"]}}
    p = cs.build_system_prompt(cfg)
    assert "patient case" in p and "patient names" in p and "clinical methodology" in p


# ---- main() integration with a fake client -----------------------------------

class _FakeMsg:
    def __init__(self, text):
        self.content = [type("C", (), {"text": text})()]


class _FakeClient:
    def __init__(self, verdict_text):
        self._t = verdict_text
        self.messages = self

    def create(self, **kw):
        return _FakeMsg(self._t)


def _write(root, rel, body):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)


def test_main_hard_fails_on_secret(tmp_path, monkeypatch):
    root = str(tmp_path)
    _write(root, "sanitize.config.json", '{"deterministic":{"enabled":true,"allow_substrings":[]}}')
    _write(root, "hermes-skill/SKILL.md", "key sk-ant-api03-BBBBBBBBBBBBBBBBBBBBBBBB")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = cs.main(["hermes-skill/SKILL.md"], root=root)
    assert rc == 1  # deterministic hard fail regardless of semantic


def test_main_semantic_flag(tmp_path):
    root = str(tmp_path)
    _write(root, "sanitize.config.json",
           '{"sensitive_prefixes":["hermes-skill/"],"deterministic":{"enabled":true,"allow_substrings":[]},'
           '"semantic":{"domain_noun":"case","flag_examples":[],"do_not_flag_examples":[],"model":"m"}}')
    _write(root, "hermes-skill/SKILL.md", "Operation Bluebird targeted Acme Corp on 2024-01-02.")
    os.environ["ANTHROPIC_API_KEY"] = "test"
    try:
        rc = cs.main(["hermes-skill/SKILL.md"], root=root,
                     client_factory=lambda: _FakeClient('{"flagged": true, "reasons": ["case codename"]}'))
    finally:
        del os.environ["ANTHROPIC_API_KEY"]
    assert rc == 1


def test_main_clean_passes(tmp_path):
    root = str(tmp_path)
    _write(root, "sanitize.config.json",
           '{"sensitive_prefixes":["hermes-skill/"],"deterministic":{"enabled":true,"allow_substrings":[]},'
           '"semantic":{"domain_noun":"case","flag_examples":[],"do_not_flag_examples":[],"model":"m"}}')
    _write(root, "hermes-skill/SKILL.md", "Generic methodology: grade sources A-F.")
    os.environ["ANTHROPIC_API_KEY"] = "test"
    try:
        rc = cs.main(["hermes-skill/SKILL.md"], root=root,
                     client_factory=lambda: _FakeClient('{"flagged": false, "reasons": []}'))
    finally:
        del os.environ["ANTHROPIC_API_KEY"]
    assert rc == 0


def test_main_require_semantic_fails_without_key(tmp_path, monkeypatch):
    root = str(tmp_path)
    _write(root, "sanitize.config.json", '{"sensitive_prefixes":["hermes-skill/"]}')
    _write(root, "hermes-skill/SKILL.md", "generic text")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = cs.main(["--require-semantic", "hermes-skill/SKILL.md"], root=root)
    assert rc == 2


def test_skip_paths_excludes_fixtures_from_deterministic(tmp_path, monkeypatch):
    root = str(tmp_path)
    _write(root, "sanitize.config.json",
           '{"deterministic":{"enabled":true,"allow_substrings":[],"skip_paths":["tests/"]}}')
    _write(root, "tests/fixtures.py", "fake AKIA1234567890ABCDEF in a test fixture")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = cs.main(["tests/fixtures.py"], root=root)
    assert rc == 0  # skipped, not flagged


def test_full_tree_mode_scans_tracked_files(tmp_path, monkeypatch):
    root = str(tmp_path)
    subprocess.run(["git", "init", "-q", root], check=True)
    subprocess.run(["git", "-C", root, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", root, "config", "user.name", "t"], check=True)
    _write(root, "sanitize.config.json", '{"deterministic":{"enabled":true,"allow_substrings":[]}}')
    _write(root, "notes.md", "leaked AKIA1234567890ABCDEF here")
    subprocess.run(["git", "-C", root, "add", "-A"], check=True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = cs.main(["--full-tree"], root=root)
    assert rc == 1  # AKIA key caught in full-tree sweep
