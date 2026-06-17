"""Bibliography parsing — turn BibTeX and loose DOI lists into ``Reference``s.

Stdlib-only (no ``bibtexparser`` dependency) so the engine stays import-light. The
BibTeX parser is brace-balanced and handles the common field shapes
(``field = {value}`` / ``"value"`` / bareword) and the ``A and B and C`` author
convention. It is not a full BibTeX grammar — it targets real-world reference
lists, not every edge of the format.
"""
from __future__ import annotations

import re

from .citations import Reference, _normalize_doi


def _strip_value(raw: str) -> str:
    """Strip surrounding {}/"" delimiters, remove nested braces, collapse space."""
    s = raw.strip().rstrip(",").strip()
    if s and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    s = s.replace("{", "").replace("}", "")
    return " ".join(s.split())


def _split_authors(value: str) -> list:
    """Split a BibTeX author value on the ' and ' separator."""
    parts = re.split(r"\s+and\s+", value.strip())
    return [p.strip() for p in parts if p.strip()]


def _iter_entry_bodies(text: str):
    """Yield (entry_type, body) for each @type{...} block, brace-balanced."""
    i, n = 0, len(text)
    while i < n:
        at = text.find("@", i)
        if at == -1:
            return
        brace = text.find("{", at)
        if brace == -1:
            return
        entry_type = text[at + 1:brace].strip().lower()
        # balance braces from `brace`
        depth, j = 0, brace
        while j < n:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = text[brace + 1:j]
        yield entry_type, body
        i = j + 1


def _parse_fields(body: str) -> dict:
    """Parse ``name = value`` fields from an entry body (skips the citekey)."""
    # Drop the citekey (everything up to the first comma).
    comma = body.find(",")
    fields_blob = body[comma + 1:] if comma != -1 else body

    fields: dict = {}
    # Match: key = {balanced} | "quoted" | bareword , at top level.
    pos, n = 0, len(fields_blob)
    key_re = re.compile(r"\s*([A-Za-z][A-Za-z0-9_-]*)\s*=\s*")
    while pos < n:
        m = key_re.match(fields_blob, pos)
        if not m:
            pos += 1
            continue
        key = m.group(1).lower()
        vstart = m.end()
        if vstart >= n:
            break
        ch = fields_blob[vstart]
        if ch == "{":
            depth, j = 0, vstart
            while j < n:
                if fields_blob[j] == "{":
                    depth += 1
                elif fields_blob[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            value = fields_blob[vstart:j + 1]
            pos = j + 1
        elif ch == '"':
            j = vstart + 1
            while j < n and fields_blob[j] != '"':
                j += 1
            value = fields_blob[vstart:j + 1]
            pos = j + 1
        else:
            j = vstart
            while j < n and fields_blob[j] != ",":
                j += 1
            value = fields_blob[vstart:j]
            pos = j + 1
        fields[key] = _strip_value(value)
    return fields


def parse_bibtex(text: str) -> list:
    """Parse a BibTeX string into a list of :class:`Reference`."""
    refs = []
    for entry_type, body in _iter_entry_bodies(text or ""):
        if entry_type in ("comment", "string", "preamble"):
            continue
        f = _parse_fields(body)
        if not f:
            continue
        year = None
        if f.get("year"):
            m = re.search(r"\d{4}", f["year"])
            if m:
                year = int(m.group(0))
        refs.append(Reference(
            raw=body.strip(),
            title=f.get("title", ""),
            authors=_split_authors(f["author"]) if f.get("author") else [],
            year=year,
            doi=f.get("doi", ""),
            venue=f.get("journal") or f.get("booktitle") or "",
            url=f.get("url", ""),
        ))
    return refs


def parse_dois(text: str) -> list:
    """Parse a newline-separated list of DOIs (bare, ``doi:`` or doi.org URLs).

    Lines that are blank or start with ``#`` are ignored, as are lines that don't
    contain a DOI-shaped token.
    """
    refs = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        doi = _normalize_doi(line)
        if re.search(r"10\.\d{4,9}/", doi):
            refs.append(Reference(doi=doi))
    return refs
