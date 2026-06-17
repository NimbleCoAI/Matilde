"""Tests for bibliography parsing — BibTeX and loose DOI lists into References."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from matilde_plugin.engine.parsing import parse_bibtex, parse_dois  # noqa: E402


SAMPLE_BIB = r"""
@article{vaswani2017attention,
  title     = {Attention Is All You Need},
  author    = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki},
  year      = {2017},
  journal   = {Advances in Neural Information Processing Systems},
  doi       = {10.48550/arXiv.1706.03762},
  url       = {https://arxiv.org/abs/1706.03762}
}

@inproceedings{he2016deep,
  title = "Deep Residual Learning for Image Recognition",
  author = "He, Kaiming and Zhang, Xiangyu",
  year = 2016
}
"""


def test_parse_bibtex_extracts_fields():
    refs = parse_bibtex(SAMPLE_BIB)
    assert len(refs) == 2
    r0 = refs[0]
    assert r0.title == "Attention Is All You Need"
    assert r0.year == 2017
    assert r0.doi == "10.48550/arXiv.1706.03762"
    assert r0.url == "https://arxiv.org/abs/1706.03762"
    assert r0.authors == ["Vaswani, Ashish", "Shazeer, Noam", "Parmar, Niki"]


def test_parse_bibtex_handles_quoted_values_and_bare_year():
    refs = parse_bibtex(SAMPLE_BIB)
    r1 = refs[1]
    assert r1.title == "Deep Residual Learning for Image Recognition"
    assert r1.year == 2016
    assert r1.authors == ["He, Kaiming", "Zhang, Xiangyu"]
    assert r1.doi == ""  # no doi present


def test_parse_bibtex_empty_string_returns_empty():
    assert parse_bibtex("") == []
    assert parse_bibtex("no entries here") == []


def test_parse_bibtex_strips_nested_braces_in_title():
    bib = r"@article{x, title = {The {BERT} Model}, year = {2019}}"
    refs = parse_bibtex(bib)
    assert refs[0].title == "The BERT Model"


def test_parse_dois_one_per_line():
    text = """
    10.1038/171737a0
    https://doi.org/10.1016/j.cell.2020.01.001
    doi:10.1234/abcd
    # a comment line, ignored
    """
    refs = parse_dois(text)
    assert [r.doi for r in refs] == ["10.1038/171737a0", "10.1016/j.cell.2020.01.001", "10.1234/abcd"]
