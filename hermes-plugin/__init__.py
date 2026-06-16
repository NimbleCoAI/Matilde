"""matilde plugin — registers Matilde's verifiable-citation tools with Hermes.

Wraps the ``engine.citations`` verifier as Hermes tools. Each tool maps to a core
operation: verify one citation, verify a whole bibliography, or quick-check a
retraction. The engine is imported at tool-invocation time (via _check_available),
so the plugin registers even if imports have issues — the gate handles execution.
"""

from __future__ import annotations

import importlib.util
import os
import sys

# ---------------------------------------------------------------------------
# Path setup — package root (engine/) is one level above this file.
# ---------------------------------------------------------------------------
_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
_PACKAGE_ROOT = os.path.normpath(os.path.join(_PLUGIN_DIR, ".."))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)

# ---------------------------------------------------------------------------
# Load tools.py from this directory (import-path agnostic).
# ---------------------------------------------------------------------------
_tools_path = os.path.join(_PLUGIN_DIR, "tools.py")
_spec = importlib.util.spec_from_file_location("_matilde_tools", _tools_path)
_tools_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tools_mod)

# ---------------------------------------------------------------------------
# Re-export schemas, handlers, and the availability gate.
# ---------------------------------------------------------------------------
VERIFY_CITATION_SCHEMA = _tools_mod.VERIFY_CITATION_SCHEMA
VERIFY_BIBLIOGRAPHY_SCHEMA = _tools_mod.VERIFY_BIBLIOGRAPHY_SCHEMA
CHECK_RETRACTION_SCHEMA = _tools_mod.CHECK_RETRACTION_SCHEMA
OPENNEURO_INFO_SCHEMA = _tools_mod.OPENNEURO_INFO_SCHEMA
OPENNEURO_SEARCH_SCHEMA = _tools_mod.OPENNEURO_SEARCH_SCHEMA
OPENNEURO_FILES_SCHEMA = _tools_mod.OPENNEURO_FILES_SCHEMA
_check_available = _tools_mod._check_available
_handle_verify_citation = _tools_mod._handle_verify_citation
_handle_verify_bibliography = _tools_mod._handle_verify_bibliography
_handle_check_retraction = _tools_mod._handle_check_retraction
_handle_openneuro_dataset_info = _tools_mod._handle_openneuro_dataset_info
_handle_openneuro_search = _tools_mod._handle_openneuro_search
_handle_openneuro_list_files = _tools_mod._handle_openneuro_list_files

# ---------------------------------------------------------------------------
# Tool registry — (tool_name, schema, handler, emoji)
# ---------------------------------------------------------------------------
_TOOLS = (
    ("matilde_verify_citation", VERIFY_CITATION_SCHEMA, _handle_verify_citation, "✓"),
    ("matilde_verify_bibliography", VERIFY_BIBLIOGRAPHY_SCHEMA, _handle_verify_bibliography, "📚"),
    ("matilde_check_retraction", CHECK_RETRACTION_SCHEMA, _handle_check_retraction, "⚠"),
    ("matilde_openneuro_dataset_info", OPENNEURO_INFO_SCHEMA, _handle_openneuro_dataset_info, "🧠"),
    ("matilde_openneuro_search", OPENNEURO_SEARCH_SCHEMA, _handle_openneuro_search, "🔎"),
    ("matilde_openneuro_list_files", OPENNEURO_FILES_SCHEMA, _handle_openneuro_list_files, "🗂"),
)


def register(ctx) -> None:
    """Register all Matilde tools. Called once by the Hermes plugin loader."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="matilde",
            schema=schema,
            handler=handler,
            check_fn=_check_available,
            emoji=emoji,
        )
