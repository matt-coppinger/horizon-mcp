"""Inventory tools: desktop pools, machines, sessions, farms, application pools."""
import asyncio
import os
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_delete, api_get, api_post, api_put

_MAX_MACHINE_COUNT = int(os.environ.get("HORIZON_MAX_MACHINE_COUNT", "500"))
_MAX_BULK_DESTRUCTIVE = int(os.environ.get("HORIZON_MAX_BULK_DESTRUCTIVE", "20"))
_DESTRUCTIVE_BULK_ACTIONS = {"rebuild", "reset", "archive"}

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

    @mcp.tool()
    async def create_desktop_pool(
        spec: Annotated[
            dict,
            "Full pool specification. Required keys: name, type (AUTOMATED | MANUAL), "
            "source (INSTANT_CLONE | VIRTUAL_CENTER | RDS), "
            "user_assignment (FLOATING | DEDICATED). "
            "AUTOMATED pools also require provisioning_settings with: virtual_center_id, "
            "parent_vm_id, snapshot_id, datacenter_id, vm_folder_id, host_or_cluster_id, "
            "resource_pool_id, datastores ([{datastore_id}]), "
            "nics ([{nic_id, network_label_id}]), naming_pattern, max_machine_count. "
            "Use list_virtual_centers, list_base_vms, list_base_vm_snapshots, "
            "list_datacenters, list_vm_folders, list_hosts_or_clusters, list_datastores, "
            "list_resource_pools, and list_network_labels to look up all required IDs.",
        ],
    ) -> dict:
        """Create a new desktop pool.

        CAUTION: Provisioning an AUTOMATED pool immediately begins creating VMs in vCenter.
        Always confirm with the user before calling this.
        """
        max_count = spec.get("provisioning_settings", {}).get("max_machine_count")
        if max_count is not None and max_count > _MAX_MACHINE_COUNT:
            raise ValueError(
                f"max_machine_count {max_count} exceeds the safety ceiling of "
                f"{_MAX_MACHINE_COUNT}. Reduce the count or raise "
                "HORIZON_MAX_MACHINE_COUNT if this is intentional."
            )
        result = await api_post("/inventory/v1/desktop-pools", spec)
        if result is None:
            raise ValueError(
                "Pool creation returned no response body — the pool may not have been "
                "created. Check Horizon audit logs before retrying."
            )
        return result

    @mcp.tool()
    async def update_desktop_pool(
        pool_id: Annotated[str, "Desktop pool ID — obtain from list_desktop_pools"],
        spec: Annotated[
            dict,
            "Updated pool specification. Retrieve the current config with get_desktop_pool, "
            "modify the relevant fields, and pass the result here. Omit read-only fields "
            "such as id, type, and source.",
        ],
    ) -> dict:
        """Update an existing desktop pool's configuration."""
        result = await api_put(f"/inventory/v1/desktop-pools/{pool_id}", spec)
        return result or {"success": True, "pool_id": pool_id}

    @mcp.tool()
    async def delete_desktop_pool(
        pool_id: Annotated[str, "Desktop pool ID — obtain from list_desktop_pools"],
        confirm: Annotated[
            bool,
            "Must be explicitly True to proceed. Before setting this, call get_desktop_pool "
            "and list_sessions (filtered by desktop_pool_id) to verify the pool is safe to "
            "delete, then obtain explicit user approval.",
        ] = False,
    ) -> dict:
        """Delete a desktop pool and all of its machines.

        CAUTION: This is irreversible. All machines in the pool are deleted and any active
        user sessions are terminated. Always confirm with the user before calling this.
        """
        if not confirm:
            raise ValueError(
                "confirm=True is required. First call get_desktop_pool and list_sessions "
                "(filter by desktop_pool_id) to verify no active sessions exist, then "
                "obtain explicit user approval before re-calling with confirm=True."
            )
        result = await api_delete(f"/inventory/v1/desktop-pools/{pool_id}")
        return result or {"success": True, "pool_id": pool_id}

    @mcp.tool()
    async def desktop_pool_action(
        pool_ids: Annotated[list[str], "List of desktop pool IDs to act on"],
        action: Annotated[
            Literal["enable", "disable", "enable-provisioning", "disable-provisioning"],
            "enable: allow new sessions. "
            "disable: prevent new sessions (existing sessions continue). "
            "enable-provisioning: resume VM provisioning. "
            "disable-provisioning: pause VM provisioning — use during maintenance windows.",
        ],
    ) -> dict:
        """Enable, disable, or toggle provisioning for one or more desktop pools.

        enable/disable controls whether new user sessions can be established.
        enable-provisioning/disable-provisioning controls whether new VMs are provisioned.
        Disabling provisioning is the correct way to pause scale-out during maintenance.
        """
        result = await api_post(f"/inventory/v1/desktop-pools/action/{action}", pool_ids)
        return result or {"success": True, "action": action, "pool_count": len(pool_ids)}

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
        if action in _DESTRUCTIVE_BULK_ACTIONS and len(machine_ids) > _MAX_BULK_DESTRUCTIVE:
            raise ValueError(
                f"Refusing to {action} {len(machine_ids)} machines in one call "
                f"(limit: {_MAX_BULK_DESTRUCTIVE}). Split into smaller batches and confirm "
                "with the user before each batch. Raise HORIZON_MAX_BULK_DESTRUCTIVE to "
                "increase the limit if this is intentional."
            )
        path, body_style = _MACHINE_ACTIONS[action]
        if body_style == "object":
            body: list | dict = {"machineIds": machine_ids, "forceOperation": force}
        else:
            body = machine_ids
        result = await api_post(path, body)
        return result or {"success": True, "action": action, "machine_count": len(machine_ids)}

    @mcp.tool()
    async def assign_machine_users(
        machine_id: Annotated[str, "Machine ID — obtain from list_machines"],
        user_ids: Annotated[
            list[str],
            "AD user IDs to assign or unassign. Use search_ad_users_or_groups to find IDs.",
        ],
        action: Annotated[
            Literal["assign", "unassign"],
            "assign: assign users to this dedicated desktop. "
            "unassign: remove existing user assignment.",
        ],
    ) -> dict:
        """Assign or unassign users to a dedicated desktop machine.

        Only applicable to machines in dedicated (non-floating) desktop pools.
        A machine can only have one assigned user at a time in most pool configurations.
        """
        endpoint = "assign-users" if action == "assign" else "unassign-users"
        result = await api_post(
            f"/inventory/v1/machines/{machine_id}/action/{endpoint}",
            {"user_ids": user_ids},
        )
        return result or {"success": True, "action": action, "machine_id": machine_id}

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

    @mcp.tool()
    async def create_rdsh_farm(
        spec: Annotated[
            dict,
            "Full farm specification. Required keys: name, type (AUTOMATED | MANUAL), "
            "source (INSTANT_CLONE | RDS). AUTOMATED farms also require provisioning_settings "
            "with the same fields as create_desktop_pool (virtual_center_id, parent_vm_id, "
            "snapshot_id, datacenter_id, vm_folder_id, host_or_cluster_id, resource_pool_id, "
            "datastores, nics, naming_pattern, max_machine_count). "
            "settings.desktop_id links the farm to its RDS desktop pool. "
            "Use list_virtual_centers, list_base_vms, list_base_vm_snapshots, "
            "list_datacenters, list_vm_folders, list_hosts_or_clusters, list_datastores, "
            "list_resource_pools, and list_network_labels to look up all required IDs.",
        ],
    ) -> dict:
        """Create a new RDS farm.

        CAUTION: Provisioning an AUTOMATED farm immediately begins creating VMs in vCenter.
        Always confirm with the user before calling this.
        """
        max_count = spec.get("provisioning_settings", {}).get("max_machine_count")
        if max_count is not None and max_count > _MAX_MACHINE_COUNT:
            raise ValueError(
                f"max_machine_count {max_count} exceeds the safety ceiling of "
                f"{_MAX_MACHINE_COUNT}. Reduce the count or raise "
                "HORIZON_MAX_MACHINE_COUNT if this is intentional."
            )
        result = await api_post("/inventory/v1/farms", spec)
        if result is None:
            raise ValueError(
                "Farm creation returned no response body — the farm may not have been "
                "created. Check Horizon audit logs before retrying."
            )
        return result

    @mcp.tool()
    async def update_rdsh_farm(
        farm_id: Annotated[str, "Farm ID — obtain from list_rdsh_farms"],
        spec: Annotated[
            dict,
            "Updated farm specification. Retrieve the current config with get_rdsh_farm, "
            "modify the relevant fields, and pass the result here. Omit read-only fields "
            "such as id, type, and source.",
        ],
    ) -> dict:
        """Update an existing RDS farm's configuration."""
        result = await api_put(f"/inventory/v1/farms/{farm_id}", spec)
        return result or {"success": True, "farm_id": farm_id}

    @mcp.tool()
    async def delete_rdsh_farm(
        farm_id: Annotated[str, "Farm ID — obtain from list_rdsh_farms"],
        confirm: Annotated[
            bool,
            "Must be explicitly True to proceed. Before setting this, call get_rdsh_farm "
            "and list_sessions to verify the farm has no active sessions, then obtain "
            "explicit user approval.",
        ] = False,
    ) -> dict:
        """Delete an RDS farm and all of its servers.

        CAUTION: This is irreversible. All servers in the farm are deleted and any active
        user sessions are terminated. Always confirm with the user before calling this.
        """
        if not confirm:
            raise ValueError(
                "confirm=True is required. First call get_rdsh_farm and list_sessions to "
                "verify no active sessions exist, then obtain explicit user approval before "
                "re-calling with confirm=True."
            )
        result = await api_delete(f"/inventory/v1/farms/{farm_id}")
        return result or {"success": True, "farm_id": farm_id}

    @mcp.tool()
    async def rdsh_farm_action(
        farm_ids: Annotated[list[str], "List of RDS farm IDs to act on"],
        action: Annotated[
            Literal["enable", "disable"],
            "enable: allow new sessions to this farm. "
            "disable: prevent new sessions (existing sessions continue until they end).",
        ],
    ) -> dict:
        """Enable or disable one or more RDS farms.

        Disabling a farm prevents new sessions from being routed to it
        without terminating existing sessions — useful for draining a farm before maintenance.

        Unlike desktop pools, farms have no bulk enable/disable endpoint — this sends one
        PUT per farm with just {"enabled": ...} in the body and reports per-farm results
        if any fail.

        CAVEAT: the Horizon API's farm update schema formally requires several other fields
        (access_group_id, display_name, display_protocol_settings, server_error_threshold,
        session_settings, use_custom_script_for_load_balancing) that this tool does not send —
        some of those aren't even retrievable from get_rdsh_farm, so a full spec can't always
        be reconstructed. If a farm's Horizon instance enforces that requirement strictly,
        this call will fail per-farm with a 400 error naming the missing field(s); the errors
        field in the response will show which farms failed and why.
        """
        enabled = action == "enable"
        coros = [api_put(f"/inventory/v1/farms/{farm_id}", {"enabled": enabled}) for farm_id in farm_ids]
        results = await asyncio.gather(*coros, return_exceptions=True)
        errors = {farm_id: str(r) for farm_id, r in zip(farm_ids, results) if isinstance(r, Exception)}
        return {
            "action": action,
            "farm_count": len(farm_ids),
            "succeeded": len(farm_ids) - len(errors),
            **({"errors": errors} if errors else {}),
        }

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

    @mcp.tool()
    async def create_application_pool(
        name: Annotated[str, "Internal name (no spaces recommended)"],
        farm_id: Annotated[str, "RDS farm ID — obtain from list_rdsh_farms"],
        executable_path: Annotated[
            str,
            r"Full path to the executable or .lnk shortcut, "
            r"e.g. C:\ProgramData\Microsoft\Windows\Start Menu\Programs\MyApp.lnk",
        ],
        display_name: Annotated[str, "User-visible display name (defaults to name)"] = "",
        publisher: Annotated[str, "Publisher name shown in the app catalog"] = "",
        version: Annotated[str, "Application version string"] = "",
        enable_pre_launch: Annotated[bool, "Pre-launch the app before the user connects"] = False,
        enable_client_restrictions: Annotated[bool, "Restrict which clients can launch the app"] = False,
        multi_session_mode: Annotated[
            Literal["DISABLED", "ENABLED_DEFAULT_OFF", "ENABLED_DEFAULT_ON"],
            "Multi-session mode: DISABLED (one session per user), "
            "ENABLED_DEFAULT_OFF, or ENABLED_DEFAULT_ON.",
        ] = "DISABLED",
    ) -> dict:
        """Publish a new application pool from an RDS farm."""
        body: dict = {
            "name": name,
            "farm_id": farm_id,
            "executable_path": executable_path,
            "enable_pre_launch": enable_pre_launch,
            "enable_client_restrictions": enable_client_restrictions,
            "multi_session_mode": multi_session_mode,
        }
        if display_name:
            body["display_name"] = display_name
        if publisher:
            body["publisher"] = publisher
        if version:
            body["version"] = version
        result = await api_post("/inventory/v1/application-pools", body)
        return result or {"success": True}

    @mcp.tool()
    async def update_application_pool(
        pool_id: Annotated[str, "Application pool ID — obtain from list_application_pools"],
        spec: Annotated[
            dict,
            "Updated application pool specification. Retrieve the current config with "
            "get_application_pool, modify the relevant fields, and pass the result here.",
        ],
    ) -> dict:
        """Update an existing application pool's configuration."""
        result = await api_put(f"/inventory/v1/application-pools/{pool_id}", spec)
        return result or {"success": True, "pool_id": pool_id}

    @mcp.tool()
    async def delete_application_pool(
        pool_id: Annotated[str, "Application pool ID — obtain from list_application_pools"],
        confirm: Annotated[
            bool,
            "Must be explicitly True to proceed. Obtain explicit user approval before setting.",
        ] = False,
    ) -> dict:
        """Delete a published application pool.

        CAUTION: Users will immediately lose access to this application.
        Always confirm with the user before calling this.
        """
        if not confirm:
            raise ValueError(
                "confirm=True is required. Obtain explicit user approval before "
                "re-calling with confirm=True."
            )
        result = await api_delete(f"/inventory/v1/application-pools/{pool_id}")
        return result or {"success": True, "pool_id": pool_id}

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
    async def reset_or_restart_sessions(
        session_ids: Annotated[list[str], "List of session IDs to act on"],
        action: Annotated[
            Literal["reset", "restart"],
            "reset: hard power-cycle the VM (immediate, may cause data loss). "
            "restart: graceful reboot of the VM (user is logged off first).",
        ],
    ) -> dict:
        """Reset or restart the virtual machine backing one or more sessions.

        CAUTION: Both actions will terminate the user's session.
        reset is a hard power-cycle and may cause data loss.
        restart attempts a graceful reboot but the session will still end.
        Always confirm with the user before calling this.
        """
        result = await api_post(f"/inventory/v1/sessions/action/{action}", session_ids)
        return result or {"success": True, "action": action, "session_count": len(session_ids)}

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
