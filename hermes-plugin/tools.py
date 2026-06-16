"""{{package}} tools for Hermes — schemas, handlers, and the availability gate.

This file is loaded by __init__.py via importlib so it works under any
import path Hermes assigns to the plugin. It must be importable with no
external dependencies beyond the stdlib and whatever your package library
provides.

INSTANTIATION GUIDE
-------------------
1. Fill in _check_available() to test that your library / API creds / data
   store are actually reachable. Return True to allow invocation, False to
   block it with a clear error message surfaced by Hermes.

2. Copy the EXAMPLE_SCHEMA + _handle_example block as many times as you need
   real tools. Rename every occurrence of "example" and "EXAMPLE".

3. Export each new schema and handler from this module — __init__.py imports
   them by name. Add a line for each to the import block in __init__.py and
   a row to _TOOLS.

4. Delete the example tool (schema, handler, and its _TOOLS row) once you
   have at least one real tool working end-to-end.

No classes required. Keep handlers as plain functions: (args: dict, **kwargs)
-> str (a JSON string). The _tool_result / _tool_error helpers standardise
the envelope.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
# Mirrors the path insert in __init__.py so this file is also independently
# importable (e.g. in unit tests that import tools.py directly).
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_ROOT = os.path.normpath(os.path.join(_PLUGIN_DIR, ".."))
if _PACKAGE_ROOT not in sys.path:
    sys.path.insert(0, _PACKAGE_ROOT)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _tool_result(data: Any = None, **kwargs: Any) -> str:
    """Return a JSON success envelope.

    Pass either a single dict as `data`, or keyword arguments that become
    the top-level keys. `success: true` is always injected.

        _tool_result({"count": 3, "items": [...]})
        _tool_result(count=3, items=[...])
    """
    if data is not None:
        payload = data if isinstance(data, dict) else {"result": data}
    else:
        payload = kwargs
    payload.setdefault("success", True)
    return json.dumps(payload, default=str)


def _tool_error(message: str, **extra: Any) -> str:
    """Return a JSON error envelope.

    The `error` key carries the human-readable message. `success: false` is
    always set. Pass extra keyword arguments for structured debugging info.

        _tool_error("API key missing", hint="set {{YOUR_API_KEY}} in .env")
    """
    payload = {"error": message, "success": False, **extra}
    return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Availability gate
# ---------------------------------------------------------------------------

def _check_available() -> bool:
    """Return True if this plugin's tools are ready to run.

    Called by Hermes before every tool invocation. If this returns False,
    Hermes surfaces an error to the agent without calling the handler.

    WHAT TO CHECK HERE:
    - Can the library be imported? (try/except ImportError)
    - Are required env vars set? (os.environ.get)
    - Is a required local file or database present? (os.path.exists)
    - Can a lightweight connectivity check pass? (optional — only if cheap)

    Keep this fast. Do NOT open connections or read large files; just verify
    prerequisites exist. Actual errors inside handlers are reported via
    _tool_error, not this gate.

    EXAMPLE — check that your library is importable AND a required env var is set:

        def _check_available() -> bool:
            try:
                import {{package_lib}}          # noqa: F401
            except ImportError:
                return False
            if not os.environ.get("{{YOUR_API_KEY}}"):
                return False
            return True
    """
    # TODO: replace the body below with your real availability check.
    try:
        # Replace with: `import {{package_lib}}`
        # If your package has no importable library (e.g. it only calls an
        # external API), just check for the required env var instead.
        _api_key = os.environ.get("{{YOUR_API_KEY}}")
        if not _api_key:
            return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Example tool
# ---------------------------------------------------------------------------
# This is the minimum viable tool: one schema, one handler.
# Copy this block to add a real tool, then delete the example.

EXAMPLE_SCHEMA = {
    # Must match the tool_name in __init__.py's _TOOLS tuple exactly.
    "name": "{{package}}_example",

    # Shown to the agent in the tool listing. Be specific: what does this
    # tool do, what does it return, when should the agent call it?
    "description": (
        "Example tool for the {{package}} package. "
        "Replace this description with what your tool actually does. "
        "Include what the agent should pass as input and what it gets back."
    ),

    # JSON Schema for the tool's input arguments.
    # Hermes validates incoming args against this before calling the handler.
    "parameters": {
        "type": "object",
        "properties": {
            # REPLACE: define the real parameters your tool needs.
            # Each key becomes an args["key"] in the handler.
            "query": {
                "type": "string",
                "description": (
                    "The input query or identifier this tool operates on. "
                    "Replace with a parameter name and description appropriate "
                    "for your domain (e.g. 'subject', 'target_id', 'url')."
                ),
            },
            "options": {
                "type": "object",
                "description": (
                    "Optional dict of extra parameters. Replace or remove once "
                    "you know your tool's real parameter surface."
                ),
            },
        },
        # List the parameter names the handler cannot function without.
        "required": ["query"],
    },
}


def _handle_example(args: dict[str, Any], **kwargs: Any) -> str:
    """Handle a call to {{package}}_example.

    Hermes calls this function after _check_available() returns True.

    Args:
        args:    Validated input dict matching EXAMPLE_SCHEMA["parameters"].
        **kwargs: Reserved for future Hermes context keys (e.g. session_id).
                 Always accept **kwargs even if you don't use them.

    Returns:
        A JSON string produced by _tool_result() or _tool_error().
        Never raise — catch all exceptions and return _tool_error(...).

    HANDLER PATTERN:
        1. Extract and validate inputs from args (required fields first).
        2. Call your library / API / local engine.
        3. Shape the response into a dict and return _tool_result(...).
        4. Wrap the body in a try/except and return _tool_error on failure.

    EXAMPLE — calling a hypothetical library function:

        from {{package_lib}} import run_query, QueryError

        query = args.get("query", "").strip()
        if not query:
            return _tool_error("'query' must not be empty.")

        try:
            result = run_query(query, **args.get("options", {}))
        except QueryError as exc:
            return _tool_error(f"Query failed: {exc}")

        return _tool_result(
            query=query,
            result_count=len(result.items),
            items=result.items,
            message=f"Found {len(result.items)} results for '{query}'.",
        )
    """
    # --- Input extraction ---
    query = args.get("query", "").strip()
    if not query:
        return _tool_error("'query' must not be empty.")

    options = args.get("options") or {}

    # --- TODO: replace the stub below with your real implementation ---
    try:
        # Placeholder: echo the query back with a stub result.
        # Delete this block and call your actual library here.
        stub_result = {
            "query": query,
            "options": options,
            "items": [],
            "note": (
                "This is the example stub. Replace _handle_example with a "
                "real implementation that calls your {{package}} library."
            ),
        }
        return _tool_result(stub_result)

    except Exception as exc:
        # Catch-all: surface unexpected errors as tool errors rather than
        # letting them propagate and crash the Hermes tool dispatch loop.
        return _tool_error(
            f"{{package}}_example failed: {type(exc).__name__}: {exc}",
            query=query,
        )


# ---------------------------------------------------------------------------
# Add your real tools below this line
# ---------------------------------------------------------------------------
# Template for each additional tool:
#
# YOUR_TOOL_SCHEMA = {
#     "name": "{{package}}_<verb>",
#     "description": "...",
#     "parameters": {
#         "type": "object",
#         "properties": {
#             "<param>": {"type": "string", "description": "..."},
#         },
#         "required": ["<param>"],
#     },
# }
#
# def _handle_<verb>(args: dict[str, Any], **kwargs: Any) -> str:
#     <param> = args.get("<param>", "")
#     if not <param>:
#         return _tool_error("'<param>' is required.")
#     try:
#         result = your_library_call(<param>)
#         return _tool_result(result=result)
#     except Exception as exc:
#         return _tool_error(f"<verb> failed: {exc}")
