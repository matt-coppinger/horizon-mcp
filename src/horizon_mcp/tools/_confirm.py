"""Human-in-the-loop confirmation for destructive tools, via MCP elicitation.

A confirm=True argument can't prove a human approved anything — the model sets it.
Elicitation pauses the tool call and asks the user directly through the MCP client,
and the model cannot answer on the user's behalf.

HORIZON_CONFIRMATION controls what happens when the client doesn't support
elicitation:
  elicit (default)  refuse — the operation can't run without a real user prompt
  flag              fall back to the tool's confirm=True argument
"""
import os

import mcp.types as mt
from fastmcp.server.dependencies import get_context

PROCEED = "Proceed"
CANCEL = "Cancel"


class ConfirmationRequired(ValueError):
    """Raised when a destructive operation was not confirmed by the user."""


def _mode() -> str:
    return os.environ.get("HORIZON_CONFIRMATION", "elicit").strip().lower()


def _client_supports_elicitation(ctx) -> bool:
    try:
        return ctx.session.check_client_capability(mt.ClientCapabilities(elicitation=mt.ElicitationCapability()))
    except Exception:
        return False


async def require_confirmation(summary: str, *, confirm: bool = False) -> None:
    """Block until the user approves `summary`, or raise ConfirmationRequired.

    `summary` is shown to the user verbatim — say exactly what will happen and to what.
    """
    summary = summary.rstrip(". ")
    try:
        ctx = get_context()
    except RuntimeError:
        ctx = None

    if ctx is not None and _client_supports_elicitation(ctx):
        result = await ctx.elicit(
            f"{summary}.\n\nProceed?",
            response_type=[PROCEED, CANCEL],
            response_title="Confirm",
        )
        if getattr(result, "action", None) == "accept" and getattr(result, "data", None) == PROCEED:
            return
        raise ConfirmationRequired(
            f"Cancelled by the user — nothing was changed ({summary}). Don't retry unless the user asks."
        )

    if _mode() == "flag":
        if confirm:
            return
        raise ConfirmationRequired(
            f"confirm=True is required for: {summary}. Show the user exactly what will happen and "
            "get their explicit approval before re-calling with confirm=True."
        )

    raise ConfirmationRequired(
        f"This operation needs the user's confirmation, but the MCP client doesn't support "
        f"elicitation (in-client confirmation prompts), so it was refused: {summary}. Use a client "
        "that supports elicitation, or have the server operator set HORIZON_CONFIRMATION=flag to "
        "accept a confirm=True argument instead."
    )
