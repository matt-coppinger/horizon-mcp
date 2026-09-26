"""Help Desk tools: session diagnostics, performance data, remote assistance."""
import asyncio
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_get, api_post, seg
from ._annotations import DESTRUCTIVE, READ_ONLY
from ._confirm import require_confirmation

_DIAGNOSTIC_ASPECTS: dict[str, tuple[str, str]] = {
    "logon_timing": ("/helpdesk/v3/logon-timing/logon-segment", "dict"),
    "display_performance": ("/helpdesk/v3/performance/display-protocol", "dict"),
    "historical_performance": ("/helpdesk/v2/performance/historical-data", "dict"),
    "processes": ("/helpdesk/v2/performance/process", "list"),
    "remote_applications": ("/helpdesk/v2/performance/remote-application", "list"),
}

DiagnosticAspect = Literal[
    "logon_timing", "display_performance", "historical_performance",
    "processes", "remote_applications",
]


async def _internal_session_id(session_id: str) -> str:
    """The session's internal_session_id, which the help desk endpoints require.

    The v1 session API (used by list_sessions / get_session) doesn't return it; v3 is the
    oldest session API that does.
    """
    session = await api_get(f"/inventory/v3/sessions/{seg(session_id)}")
    internal_id = (session or {}).get("internal_session_id")
    if not internal_id:
        raise ValueError(f"Session {session_id} has no internal_session_id — cannot fetch help desk data for it")
    return internal_id


def register(mcp: FastMCP) -> None:

    @mcp.tool(annotations=READ_ONLY)
    async def diagnose_session(
        session_id: Annotated[str, "Session ID to diagnose"],
        aspects: Annotated[
            list[DiagnosticAspect] | None,
            "Diagnostic data to retrieve: logon_timing, display_performance, "
            "historical_performance, processes, remote_applications. "
            "Defaults to all aspects.",
        ] = None,
    ) -> dict:
        """Retrieve diagnostic information for a user session in a single call.

        Fetches any combination of: logon timing breakdown, real-time display protocol
        metrics, 15-minute historical performance, running processes, and active remote
        applications. Results are keyed by aspect name; a failed aspect returns
        {"error": "<message>"} rather than failing the whole call.

        The help desk endpoints take the session's internal_session_id, not its id (verified
        live: passing the id returns "Session with requested id was not found"), so this looks
        the session up first to get it.
        """
        selected = list(_DIAGNOSTIC_ASPECTS) if aspects is None else list(aspects)
        unknown = [a for a in selected if a not in _DIAGNOSTIC_ASPECTS]
        if unknown:
            raise ValueError(
                f"Unknown aspects: {unknown}. Valid options: {list(_DIAGNOSTIC_ASPECTS)}"
            )
        internal_id = await _internal_session_id(session_id)
        coros = [
            api_get(_DIAGNOSTIC_ASPECTS[a][0], params={"internal_session_id": internal_id})
            for a in selected
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)
        empty: dict[str, object] = {"list": [], "dict": {}}
        return {
            aspect: ({"error": str(r)} if isinstance(r, Exception) else (r or empty[_DIAGNOSTIC_ASPECTS[aspect][1]]))
            for aspect, r in zip(selected, results)
        }

    @mcp.tool(annotations=READ_ONLY)
    async def get_remote_assistance_ticket(
        session_id: Annotated[str, "Session ID"],
    ) -> dict:
        """Generate a Microsoft Remote Assistance ticket for a user session.

        Returns an MSRA connection ticket that allows a help desk technician
        to view and control the user's desktop session.
        """
        # v1 takes the session's `id` (what list_sessions / get_session return). v2 takes a
        # different internal_session_id, which the v1 session endpoints don't expose — passing
        # the session id there returned "Session with requested id was not found" (verified live).
        return await api_get(
            "/helpdesk/v1/remote-assistant-ticket",
            params={"session_id": session_id},
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def end_remote_application(
        session_id: Annotated[str, "Session ID"],
        remote_application_id: Annotated[
            str,
            "Remote application ID to terminate. Use diagnose_session with aspects=['remote_applications'] to find IDs.",
        ],
        confirm: Annotated[
            bool,
            "Only used when the server runs with HORIZON_CONFIRMATION=flag (clients without "
            "elicitation). Otherwise the user is asked to confirm directly in the client.",
        ] = False,
    ) -> dict:
        """Terminate a specific remote application running in a session.

        CAUTION: The application will be force-closed. Unsaved data will be lost.
        Confirm with the user before calling this.
        """
        await require_confirmation(
            f"Force-close remote application {remote_application_id} in session {session_id}. "
            "Unsaved work in it is lost.",
            confirm=confirm,
        )
        result = await api_post(
            "/helpdesk/v1/performance/remote-application/action/end-remote-application",
            params={"session_id": session_id, "remote_application_id": remote_application_id},
        )
        return result or {"success": True}
