"""Help Desk tools: session diagnostics, performance data, remote assistance."""
import asyncio
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_get, api_post
from ._annotations import DESTRUCTIVE, READ_ONLY

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
        applications. Results are keyed by aspect name; a failed aspect returns its error
        message as a string rather than failing the whole call.

        """
        selected = list(_DIAGNOSTIC_ASPECTS) if aspects is None else list(aspects)
        unknown = [a for a in selected if a not in _DIAGNOSTIC_ASPECTS]
        if unknown:
            raise ValueError(
                f"Unknown aspects: {unknown}. Valid options: {list(_DIAGNOSTIC_ASPECTS)}"
            )
        coros = [
            api_get(_DIAGNOSTIC_ASPECTS[a][0], params={"internal_session_id": session_id})
            for a in selected
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)
        empty: dict[str, object] = {"list": [], "dict": {}}
        return {
            aspect: (str(r) if isinstance(r, Exception) else (r or empty[_DIAGNOSTIC_ASPECTS[aspect][1]]))
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
        return await api_get(
            "/helpdesk/v2/remote-assistant-ticket",
            params={"internal_session_id": session_id},
        )

    @mcp.tool(annotations=DESTRUCTIVE)
    async def end_remote_application(
        session_id: Annotated[str, "Session ID"],
        remote_application_id: Annotated[
            str,
            "Remote application ID to terminate. Use diagnose_session with aspects=['remote_applications'] to find IDs.",
        ],
    ) -> dict:
        """Terminate a specific remote application running in a session.

        CAUTION: The application will be force-closed. Unsaved data will be lost.
        Confirm with the user before calling this.
        """
        result = await api_post(
            "/helpdesk/v1/performance/remote-application/action/end-remote-application",
            params={"session_id": session_id, "remote_application_id": remote_application_id},
        )
        return result or {"success": True}
