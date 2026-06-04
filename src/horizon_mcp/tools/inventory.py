"""Inventory tools: desktop pools, machines, sessions, farms, application pools."""
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_get, api_post

_MACHINE_ACTIONS = {
    "shutdown": ("/inventory/v1/machines/action/shutdown", "object"),
    "restart": ("/inventory/v1/machines/action/restart", "object"),
    "reset": ("/inventory/v1/machines/action/reset", "array"),
    "rebuild": ("/inventory/v1/machines/action/rebuild", "array"),
    "recover": ("/inventory/v1/machines/action/recover", "array"),
    "enter_maintenance": ("/inventory/v1/machines/action/enter-maintenance", "array"),
    "exit_maintenance": ("/inventory/v1/machines/action/exit-maintenance", "array"),
    "archive": ("/inventory/v1/machines/action/archive", "array"),
}

_FORCE_APPLICABLE_ACTIONS = {"shutdown", "restart"}


def register(mcp: FastMCP) -> None:

    # ── Desktop Pools ──────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_desktop_pools(
        page: Annotated[int, "Page number (1-based)"] = 1,
        size: Annotated[int, "Results per page (max 1000)"] = 100,
        filter: Annotated[
            str,
            'Horizon filter JSON string. Example: {"type":"Contains","name":"name","value":"dev"}'
            " — see Horizon REST API docs for full filter syntax.",
        ] = "",
    ) -> list:
        """List all desktop pools (VDI and RDS) in the Horizon environment."""
        params: dict = {"page": page, "size": size}
        if filter:
            params["filter"] = filter
        return await api_get("/inventory/v1/desktop-pools", params) or []

    @mcp.tool()
    async def get_desktop_pool(
        pool_id: Annotated[str, "Desktop pool ID — obtain from list_desktop_pools"],
    ) -> dict:
        """Get detailed configuration and status of a specific desktop pool."""
        return await api_get(f"/inventory/v1/desktop-pools/{pool_id}")

    # ── Machines ───────────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_machines(
        page: Annotated[int, "Page number (1-based)"] = 1,
        size: Annotated[int, "Results per page (max 1000)"] = 100,
        filter: Annotated[
            str,
            'Horizon filter JSON string. Example: {"type":"Equals","name":"desktop_pool_id","value":"<pool-id>"}',
        ] = "",
        sort_by: Annotated[str, "Field name to sort by, e.g. name"] = "",
        order_by: Annotated[str, "Sort direction: ASC or DESC"] = "",
    ) -> list:
        """List machines (virtual desktops) in the environment.

        To filter by pool, use: filter={"type":"Equals","name":"desktop_pool_id","value":"<id>"}
        To filter by state, use: filter={"type":"Equals","name":"state","value":"AVAILABLE"}
        """
        params: dict = {"page": page, "size": size}
        if filter:
            params["filter"] = filter
        if sort_by:
            params["sort_by"] = sort_by
        if order_by:
            params["order_by"] = order_by
        return await api_get("/inventory/v1/machines", params) or []

    @mcp.tool()
    async def get_machine(
        machine_id: Annotated[str, "Machine ID — obtain from list_machines"],
    ) -> dict:
        """Get detailed information about a specific machine."""
        return await api_get(f"/inventory/v1/machines/{machine_id}")

    @mcp.tool()
    async def machine_action(
        machine_ids: Annotated[list[str], "List of machine IDs to act on"],
        action: Annotated[
            Literal[
                "shutdown",
                "restart",
                "reset",
                "rebuild",
                "recover",
                "enter_maintenance",
                "exit_maintenance",
                "archive",
            ],
            "Action to perform on the machines",
        ],
        force: Annotated[
            bool,
            "Force the operation even if sessions are active. "
            "Only applies to shutdown and restart — raises an error for other actions.",
        ] = False,
    ) -> dict:
        """Perform a bulk action on one or more machines.

        Actions:
        - shutdown: gracefully power off (use force=true to override active sessions)
        - restart: reboot the machine (use force=true to override active sessions)
        - reset: hard reset (power cycle) — may cause data loss
        - rebuild: re-provision the machine from the pool's image
        - recover: recover a machine stuck in an error state
        - enter_maintenance: put machine into maintenance mode (prevents new sessions)
        - exit_maintenance: take machine out of maintenance mode
        - archive: initiate machine archival

        CAUTION: rebuild and reset are destructive and will discard unsaved user data.
        Always confirm with the user before calling these actions.
        """
        if force and action not in _FORCE_APPLICABLE_ACTIONS:
            raise ValueError(
                f"force=True is only applicable to {sorted(_FORCE_APPLICABLE_ACTIONS)}, "
                f"not '{action}'. Remove force=True or choose a different action."
            )
        path, body_style = _MACHINE_ACTIONS[action]
        if body_style == "object":
            body: list | dict = {"machineIds": machine_ids, "forceOperation": force}
        else:
            body = machine_ids
        result = await api_post(path, body)
        return result or {"success": True, "action": action, "machine_count": len(machine_ids)}

    # ── RDS Farms ──────────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_rdsh_farms(
        page: Annotated[int, "Page number (1-based)"] = 1,
        size: Annotated[int, "Results per page (max 1000)"] = 100,
        filter: Annotated[str, "Horizon filter JSON string"] = "",
    ) -> list:
        """List all RDS (Remote Desktop Session Host) farms in the environment."""
        params: dict = {"page": page, "size": size}
        if filter:
            params["filter"] = filter
        return await api_get("/inventory/v1/farms", params) or []

    @mcp.tool()
    async def get_rdsh_farm(
        farm_id: Annotated[str, "Farm ID — obtain from list_rdsh_farms"],
    ) -> dict:
        """Get detailed information about a specific RDS farm."""
        return await api_get(f"/inventory/v1/farms/{farm_id}")

    # ── Application Pools ──────────────────────────────────────────────────────

    @mcp.tool()
    async def list_application_pools(
        page: Annotated[int, "Page number (1-based)"] = 1,
        size: Annotated[int, "Results per page (max 1000)"] = 100,
        filter: Annotated[str, "Horizon filter JSON string"] = "",
    ) -> list:
        """List published application pools in the environment."""
        params: dict = {"page": page, "size": size}
        if filter:
            params["filter"] = filter
        return await api_get("/inventory/v1/application-pools", params) or []

    @mcp.tool()
    async def get_application_pool(
        pool_id: Annotated[str, "Application pool ID — obtain from list_application_pools"],
    ) -> dict:
        """Get detailed information about a specific application pool."""
        return await api_get(f"/inventory/v1/application-pools/{pool_id}")

    # ── Sessions ───────────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_sessions(
        page: Annotated[int, "Page number (1-based)"] = 1,
        size: Annotated[int, "Results per page (max 1000)"] = 100,
        filter: Annotated[
            str,
            'Horizon filter JSON string. Example: {"type":"Equals","name":"desktop_pool_id","value":"<id>"}'
            ' or {"type":"Equals","name":"user_name","value":"jsmith"}',
        ] = "",
        sort_by: Annotated[str, "Field to sort by, e.g. user_name, start_time"] = "",
        order_by: Annotated[str, "Sort direction: ASC or DESC"] = "",
    ) -> list:
        """List active user sessions in the environment.

        Common filter fields: user_name, desktop_pool_id, machine_name, client_name, state.
        Session states: CONNECTED, DISCONNECTED, PENDING.
        """
        params: dict = {"page": page, "size": size}
        if filter:
            params["filter"] = filter
        if sort_by:
            params["sort_by"] = sort_by
        if order_by:
            params["order_by"] = order_by
        return await api_get("/inventory/v1/sessions", params) or []

    @mcp.tool()
    async def get_session(
        session_id: Annotated[str, "Session ID — obtain from list_sessions"],
    ) -> dict:
        """Get detailed information about a specific user session."""
        return await api_get(f"/inventory/v1/sessions/{session_id}")

    @mcp.tool()
    async def disconnect_sessions(
        session_ids: Annotated[
            list[str],
            "List of session IDs to disconnect. The session remains active but the client is disconnected.",
        ],
    ) -> dict:
        """Disconnect one or more user sessions (sessions remain active, clients are disconnected).

        The user's applications keep running. Use logoff_sessions to fully terminate sessions.
        """
        result = await api_post("/inventory/v1/sessions/action/disconnect", session_ids)
        return result or {"success": True, "session_count": len(session_ids)}

    @mcp.tool()
    async def logoff_sessions(
        session_ids: Annotated[list[str], "List of session IDs to log off"],
        forced: Annotated[
            bool,
            "If true, log off locked sessions. If false, locked sessions are skipped.",
        ] = False,
    ) -> dict:
        """Log off one or more user sessions, terminating their running applications.

        CAUTION: This will close all running applications in the session.
        Unsaved data will be lost. Always confirm with the user before calling this.
        """
        # Horizon API expects the session ID list as the POST body and
        # forced as a URL query parameter (not a body field).
        result = await api_post(
            "/inventory/v1/sessions/action/logoff",
            session_ids,
            params={"forced": str(forced).lower()},
        )
        return result or {"success": True, "session_count": len(session_ids)}

    @mcp.tool()
    async def send_message_to_sessions(
        session_ids: Annotated[list[str], "List of session IDs to message"],
        message: Annotated[str, "Message text to display to the user(s)"],
        message_type: Annotated[
            Literal["INFO", "WARNING", "ERROR"],
            "Message severity/icon displayed in the notification",
        ] = "INFO",
    ) -> dict:
        """Send a pop-up notification message to one or more active user sessions."""
        body = {
            "session_ids": session_ids,
            "message": message,
            "message_type": message_type,
        }
        result = await api_post("/inventory/v1/sessions/action/send-message", body)
        return result or {"success": True, "session_count": len(session_ids)}
