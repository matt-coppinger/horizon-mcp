"""Help Desk tools: session diagnostics, performance data, remote assistance."""
from typing import Annotated

from fastmcp import FastMCP

from ..client import api_get, api_post


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_session_logon_timing(
        session_id: Annotated[str, "Session ID to retrieve logon timing data for"],
    ) -> dict:
        """Get detailed logon timing breakdown for a user session.

        Returns timing data for each phase of the logon process (broker, agent,
        protocol, profile load, etc.) to help diagnose slow logon issues.
        """
        return await api_get(
            "/helpdesk/v3/logon-timing/logon-segment",
            params={"session_id": session_id},
        )

    @mcp.tool()
    async def get_session_display_performance(
        session_id: Annotated[str, "Session ID"],
    ) -> dict:
        """Get real-time display protocol performance metrics for a session.

        Returns bandwidth, FPS, latency, and packet loss data for
        PCoIP or BLAST Extreme protocol sessions.
        """
        return await api_get(
            "/helpdesk/v3/performance/display-protocol",
            params={"session_id": session_id},
        )

    @mcp.tool()
    async def get_session_historical_performance(
        session_id: Annotated[str, "Session ID"],
    ) -> dict:
        """Get historical performance data for a session over the last 15 minutes.

        Returns time-series data for bandwidth, FPS, latency, and packet loss.
        Useful for identifying intermittent performance issues.
        """
        return await api_get(
            "/helpdesk/v2/performance/historical-data",
            params={"session_id": session_id},
        )

    @mcp.tool()
    async def get_session_processes(
        session_id: Annotated[str, "Session ID"],
    ) -> list:
        """List processes running in a user's virtual desktop session.

        Returns process names, IDs, CPU, and memory usage for
        diagnosing performance issues or verifying application state.
        """
        result = await api_get(
            "/helpdesk/v2/performance/process",
            params={"session_id": session_id},
        )
        return result or []

    @mcp.tool()
    async def get_remote_assistance_ticket(
        session_id: Annotated[str, "Session ID"],
    ) -> dict:
        """Generate a Microsoft Remote Assistance ticket for a user session.

        Returns an MSRA connection ticket that allows a help desk technician
        to view and control the user's desktop session.
        """
        return await api_get(
            "/helpdesk/v2/remote-assistant-ticket",
            params={"session_id": session_id},
        )

    @mcp.tool()
    async def get_session_remote_applications(
        session_id: Annotated[str, "Session ID"],
    ) -> list:
        """List remote applications running in a session.

        Returns application names and IDs for published application sessions.
        """
        result = await api_get(
            "/helpdesk/v2/performance/remote-application",
            params={"session_id": session_id},
        )
        return result or []

    @mcp.tool()
    async def end_remote_application(
        session_id: Annotated[str, "Session ID"],
        application_id: Annotated[
            str,
            "Application ID to terminate. Use get_session_remote_applications to find IDs.",
        ],
    ) -> dict:
        """Terminate a specific remote application running in a session.

        CAUTION: The application will be force-closed. Unsaved data will be lost.
        Confirm with the user before calling this.
        """
        result = await api_post(
            "/helpdesk/v1/performance/remote-application/action/end-remote-application",
            params={"session_id": session_id, "application_id": application_id},
        )
        return result or {"success": True}
