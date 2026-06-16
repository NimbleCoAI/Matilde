"""{{package}} plugin — registers {{package}} tools with the Hermes runtime.

Wraps the {{package}} Python library as Hermes tools. Each tool maps to a
core package operation: the example tool here is the minimum required entry
point; add your real tools by following the pattern in _TOOLS below.

The package library is imported at tool invocation time (not at plugin load
time) via the check_fn mechanism. This means the plugin registers successfully
even if the library has import-time issues — _check_available gates actual
execution.

INSTANTIATION STEPS:
  1. Replace {{package}} throughout with your package slug (e.g. "threatintel",
     "healthcheck", "consulting-research"). Keep it lowercase, no spaces.
  2. Add your real tool schemas and handlers to tools.py.
  3. Add each tool as a row in _TOOLS below.
  4. Remove the example tool once you have real tools.
"""

from __future__ import annotations

import importlib.util
import os
import sys

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
# When deployed as a symlink from ~/.hermes-{name}/plugins/{{package}}/ ->
# {{package}}/hermes-plugin/, the package root is one level above this file.
# Insert it so `engine`, `collectors`, or whatever your library is named can
# be imported without any install step.
_PLUGIN_DIR = os.path.dirname(os.path.realpath(__file__))
_PACKAGE_ROOT = os.path.normpath(os.path.join(_PLUGIN_DIR, ".."))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)

# ---------------------------------------------------------------------------
# Load tools.py from this directory
# ---------------------------------------------------------------------------
# spec_from_file_location avoids package-name sensitivity: works whether
# Hermes loads this as `plugins.{{package}}` or you import it directly in
# tests as `hermes_plugin`.
_tools_path = os.path.join(_PLUGIN_DIR, "tools.py")
_spec = importlib.util.spec_from_file_location("_{{package}}_tools", _tools_path)
_tools_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tools_mod)

# ---------------------------------------------------------------------------
# Re-export schemas, handlers, and the availability gate from tools.py
# ---------------------------------------------------------------------------
# Add one line per tool schema and one per handler as you add tools.
# The names here must match what you defined in tools.py.
EXAMPLE_SCHEMA = _tools_mod.EXAMPLE_SCHEMA
_check_available = _tools_mod._check_available
_handle_example = _tools_mod._handle_example

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------
# Each row: (tool_name, schema, handler, emoji)
#
# tool_name  — the string the LLM (and humans) use to call the tool.
#              Convention: {{package}}_<verb> or {{package}}_<noun>.
# schema     — JSON Schema dict describing the tool (defined in tools.py).
# handler    — callable(args: dict, **kwargs) -> str  (JSON string).
# emoji      — single character shown in the Hermes tool listing UI.
#              Pick something that conveys the tool's function at a glance.
#
# ADD YOUR TOOLS HERE — one tuple per tool, in the order you want them listed.
_TOOLS = (
    ("{{package}}_example", EXAMPLE_SCHEMA, _handle_example, "⚙"),
    # ("{{package}}_run",     RUN_SCHEMA,     _handle_run,     "▶"),
    # ("{{package}}_status",  STATUS_SCHEMA,  _handle_status,  "📊"),
)


def register(ctx) -> None:
    """Register all {{package}} tools. Called once by the Hermes plugin loader.

    ctx is the Hermes PluginContext object. Its register_tool() signature:

        ctx.register_tool(
            name: str,          # tool name (must match schema["name"])
            toolset: str,       # logical group shown in UI (use your package slug)
            schema: dict,       # full JSON Schema for the tool
            handler: callable,  # (args: dict, **kwargs) -> str
            check_fn: callable, # () -> bool — called before each invocation
            emoji: str,         # single char for the listing
        )
    """
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="{{package}}",
            schema=schema,
            handler=handler,
            check_fn=_check_available,
            emoji=emoji,
        )
