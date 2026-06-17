"""matilde plugin — registers Matilde's verifiable-citation tools with Hermes.

Wraps the bundled ``.engine.citations`` verifier as Hermes tools. Each tool maps to a core
operation: verify one citation, verify a whole bibliography, or quick-check a
retraction. The engine is imported at tool-invocation time (via _check_available),
so the plugin registers even if imports have issues — the gate handles execution.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys

# ---------------------------------------------------------------------------
# Self-contained loading.
#
# The plugin is a self-contained package: ``engine/`` lives INSIDE this dir, and
# ``tools.py`` imports it via relative imports (``from .engine.citations import …``).
# Copying ONLY this directory into another location still imports cleanly.
#
# Hermes (and the test harness) load this ``__init__.py`` directly by file path
# under the name ``matilde_plugin``. For ``tools.py``'s relative imports to
# resolve, this module must be registered in ``sys.modules`` as a package (with a
# search path) before we import ``tools``. We ensure that here, then import
# ``tools`` as a real submodule.
# ---------------------------------------------------------------------------
_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
_PKG = __name__ if __name__ != "__main__" else "matilde_plugin"

# Register THIS module as a package in sys.modules so relative imports resolve,
# even when we were loaded by file path (spec_from_file_location does not always
# pre-register the parent package or give it a search path).
_self = sys.modules.get(_PKG)
if _self is None:
    _self = sys.modules[__name__]
    sys.modules[_PKG] = _self
if getattr(_self, "__path__", None) is None:
    _self.__path__ = [_PLUGIN_DIR]  # mark as a package
if getattr(_self, "__package__", None) in (None, ""):
    _self.__package__ = _PKG

# Import tools.py as the submodule ``<pkg>.tools`` so its ``from .engine…``
# relative imports resolve against this package.
_tools_mod = importlib.import_module(f"{_PKG}.tools")

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
