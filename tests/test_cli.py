"""Offline tests for the Matilde CLI — argument handling, formatting, exit codes.

A fake ``verify_fn`` stands in for the network verifier so these run offline.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from engine import cli  # noqa: E402
from engine.citations import AxisResult, Reference, VerificationResult  # noqa: E402


def _result(ref: Reference, verdict: str = "verified", score: float = 1.0) -> VerificationResult:
    a = AxisResult(status="pass")
    return VerificationResult(reference=ref, existence=a, metadata_match=a,
                              retraction=a, url_liveness=a, score=score, verdict=verdict)


def _verifier(verdict_for):
    """Return a verify_fn that picks a verdict per reference via verdict_for(ref)."""
    def _fn(ref):
        return _result(ref, *verdict_for(ref))
    return _fn


def test_load_references_detects_bibtex():
    refs = cli.load_references("@article{x, title={A}, doi={10.1/x}}")
    assert len(refs) == 1 and refs[0].doi == "10.1/x"


def test_load_references_falls_back_to_doi_list():
    refs = cli.load_references("10.1038/171737a0\n10.1234/abcd")
    assert [r.doi for r in refs] == ["10.1038/171737a0", "10.1234/abcd"]


def test_main_single_doi_verified_exit_zero(capsys):
    code = cli.main(["--doi", "10.1038/171737a0"],
                    verify_fn=_verifier(lambda r: ("verified", 1.0)))
    out = capsys.readouterr().out
    assert code == 0
    assert "verified" in out


def test_main_flags_not_found_with_exit_one(tmp_path, capsys):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a, title={Real}, doi={10.1/real}}\n"
                   "@article{b, title={Fake}, doi={10.9/fake}}\n")

    def verdict_for(ref):
        return ("not_found", 0.1) if "fake" in ref.doi else ("verified", 1.0)

    code = cli.main([str(bib)], verify_fn=_verifier(verdict_for))
    out = capsys.readouterr().out
    assert code == 1                       # a not_found ref fails the gate
    assert "Needs attention" in out
    assert "not_found" in out


def test_main_json_output_is_valid(tmp_path, capsys):
    bib = tmp_path / "refs.bib"
    bib.write_text("@article{a, title={Real}, doi={10.1/real}}\n")
    code = cli.main([str(bib), "--json"], verify_fn=_verifier(lambda r: ("verified", 1.0)))
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["count"] == 1
    assert payload["summary"]["verified"] == 1


def test_main_email_sets_env(tmp_path):
    bib = tmp_path / "r.bib"
    bib.write_text("@article{a, doi={10.1/x}}\n")
    cli.main([str(bib), "--email", "researcher@uni.edu"],
             verify_fn=_verifier(lambda r: ("verified", 1.0)))
    assert os.environ.get("MATILDE_CONTACT_EMAIL") == "researcher@uni.edu"


def test_main_no_input_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        cli.main([], verify_fn=_verifier(lambda r: ("verified", 1.0)))
    assert exc.value.code == 2


def test_main_empty_file_returns_two(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("# just a comment\n")
    code = cli.main([str(empty)], verify_fn=_verifier(lambda r: ("verified", 1.0)))
    assert code == 2
