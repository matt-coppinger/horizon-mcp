"""Discovery tool: describes all available Horizon MCP tools and resources."""
from fastmcp import FastMCP

from ._annotations import READ_ONLY

_COVERAGE: dict = {
    "tools": {
        "auth": [
            "horizon_login — authenticate with AD credentials, returns access + refresh tokens",
            "horizon_refresh_token — refresh an expiring access token (~8h expiry)",
            "horizon_logout — invalidate current session",
        ],
        "inventory": [
            "list_desktop_pools — list all VDI and RDS desktop pools",
            "get_desktop_pool — get pool details by ID",
            "create_desktop_pool — create a new desktop pool (spec dict, see README)",
            "update_desktop_pool — update pool configuration",
            "delete_desktop_pool — delete pool and all machines (requires confirm=True)",
            "desktop_pool_action — enable/disable pool or enable/disable-provisioning",
            "list_machines — list virtual desktops (filterable by pool, state)",
            "get_machine — get machine details by ID",
            "machine_action — shutdown/restart/reset/rebuild/recover/maintenance on machines",
            "assign_machine_users — assign or unassign users to a dedicated desktop",
            "list_rdsh_farms — list RDS farms",
            "get_rdsh_farm — get farm details by ID",
            "create_rdsh_farm — create a new RDS farm (spec dict)",
            "update_rdsh_farm — update farm configuration",
            "delete_rdsh_farm — delete farm and all servers (requires confirm=True)",
            "rdsh_farm_action — enable or disable an RDS farm (best-effort partial update; "
            "may 400 on instances that strictly enforce the full farm update schema)",
            "list_application_pools — list published application pools",
            "get_application_pool — get application pool details by ID",
            "create_application_pool — publish a new application pool from an RDS farm",
            "update_application_pool — update application pool configuration",
            "delete_application_pool — unpublish an application pool (requires confirm=True)",
            "list_sessions — list active user sessions (filterable)",
            "get_session — get session details by ID",
            "disconnect_sessions — disconnect sessions (keeps VMs running)",
            "logoff_sessions — log off sessions (terminates apps and processes)",
            "reset_or_restart_sessions — hard-reset or gracefully restart the VMs backing sessions",
            "send_message_to_sessions — send a pop-up notification to sessions",
        ],
        "monitor": [
            "get_infrastructure_health — health across all components in one parallel call",
            "get_metrics — capacity metrics across all scopes in one parallel call",
            "get_connection_server_health — detailed health for a specific Connection Server",
        ],
        "config": [
            "list_connection_servers — list connection servers",
            "get_connection_server — get connection server configuration by ID",
            "list_virtual_centers — list configured vCenter Servers",
            "get_environment_properties — environment version, build, and feature flags",
            "get_settings — global Horizon settings (read; use update_settings to write)",
            "get_global_policies — USB, clipboard, and multimedia policies (read; use update_global_policies to write)",
            "update_global_policies — update USB/clipboard/multimedia policies",
            "update_settings — update a settings section (general/security/client/feature/agent-restriction)",
            "list_licenses — license list and usage status",
            "get_event_database — event database configuration",
            "list_ic_domain_accounts — instant clone domain service accounts",
            "list_image_management — IM streams, versions, or tags (pass resource param)",
            "list_gateways — registered Unified Access Gateways",
            "trigger_connection_server_backup — initiate a Connection Server LDAP backup",
        ],
        "entitlements": [
            "list_pool_entitlements — all entitlements for desktop or application pools",
            "get_pool_entitlement — users/groups entitled to a specific pool",
            "set_pool_entitlements — add, replace, or remove entitlements (desktop or application)",
        ],
        "external_and_ad": [
            "search_ad_users_or_groups — find AD users and groups (use for entitlement IDs)",
            "get_ad_user_or_group — get AD entity details by ID",
            "list_ad_domains — list configured Active Directory domains",
            "list_ad_containers — OU browser for a domain (rdn for pool customization_settings)",
            "get_domain_netbios_map — NETBIOS to DNS domain name mapping",
            "list_audit_events — administrative audit log (filterable)",
        ],
        "resource_discovery_for_pool_creation": [
            "list_virtual_centers — starting point for all vCenter ID lookups",
            "list_datacenters(vcenter_id) — datacenters in a vCenter",
            "list_hosts_or_clusters(vcenter_id, datacenter_id) — hosts and clusters",
            "list_resource_pools(vcenter_id, host_or_cluster_id) — resource pools",
            "list_datastores(vcenter_id, host_or_cluster_id) — datastores for provisioning",
            "list_network_labels(vcenter_id, host_or_cluster_id) — port groups / dvPortGroups",
            "list_network_interface_cards(vcenter_id, ...) — NIC IDs for pool NIC config",
            "list_vm_folders(vcenter_id, datacenter_id) — VM folder hierarchy",
            "list_datastore_clusters(vcenter_id, host_or_cluster_id) — Storage DRS clusters",
            "list_vm_templates(vcenter_id) — templates for full/linked-clone pools",
            "list_base_vms(vcenter_id) — base VMs for instant-clone pools",
            "list_base_vm_snapshots(vcenter_id, base_vm_id) — snapshots of a base VM",
            "list_customization_specifications(vcenter_id) — Sysprep/QuickPrep specs",
            "list_rdsh_farms — required to get farm_id for create_application_pool",
            "horizon://config/local-access-groups resource — access_group_id, required for "
            "AUTOMATED/MANUAL create_desktop_pool and required for create_rdsh_farm",
            "list_ad_domains + list_ad_containers(domain_id) — ad_container_rdn for "
            "create_desktop_pool/create_rdsh_farm customization_settings (instant clone)",
            "list_ic_domain_accounts — instant_clone_domain_account_id for "
            "create_desktop_pool/create_rdsh_farm customization_settings (instant clone)",
        ],
        "helpdesk": [
            "diagnose_session — all session diagnostics in one parallel call",
            "get_remote_assistance_ticket — MSRA ticket for remote desktop support",
            "end_remote_application — force-close a published app in a session",
        ],
    },
    "resources": {
        "description": (
            "Read-only Horizon data exposed as MCP Resources (horizon://<path>). "
            "Resources do not consume tool slots and are available for context lookups. "
            "Use your MCP client's resource listing to enumerate them."
        ),
        "config": [
            "horizon://config/roles",
            "horizon://config/permissions",
            "horizon://config/privileges",
            "horizon://config/local-access-groups",
            "horizon://config/federation-access-groups",
            "horizon://config/gateway-access-users-or-groups",
            "horizon://config/users-or-groups-global-summary",
            "horizon://config/saml-authenticators",
            "horizon://config/radius-authenticators",
            "horizon://config/gssapi-authenticators",
            "horizon://config/jwt-authenticators",
            "horizon://config/unauthenticated-access-users",
            "horizon://config/app-volumes-managers",
            "horizon://config/uem-servers",
            "horizon://config/true-sso",
            "horizon://config/true-sso-enrollment-servers",
            "horizon://config/compute-profiles",
            "horizon://config/customization-specifications",
            "horizon://config/external-deployments",
            "horizon://config/secondary-credentials",
            "horizon://config/message-clients",
            "horizon://config/rcx-servers",
            "horizon://config/settings/agent-restriction",
            "horizon://config/settings/client",
            "horizon://config/settings/feature",
            "horizon://config/settings/general",
            "horizon://config/settings/security",
            "horizon://config/pre-logon-settings",
            "horizon://config/syslog",
            "horizon://config/ceip",
            "horizon://config/url-redirection",
            "horizon://config/log-collector/log-levels",
            "horizon://config/log-collector/tasks",
        ],
        "monitor": [
            "horizon://monitor/app-volumes-managers",
            "horizon://monitor/event-database",
            "horizon://monitor/rds-servers",
            "horizon://monitor/saml-authenticators",
            "horizon://monitor/true-sso",
            "horizon://monitor/datastores/usage-metrics",
            "horizon://monitor/pods",
            "horizon://monitor/pods/global-session-metrics",
            "horizon://monitor/message-clients",
        ],
    },
    "not_yet_supported": [
        "Federation/CPA management (initialize/join/unjoin pods, home sites, pod assignments)",
        "Image push/apply workflows (schedule-push-image, apply-image, promote-pending-image)",
        "RDS server management (list, recover, register/remove individual RDS servers within "
        "farms, schedule/cancel farm maintenance, validate installed applications)",
        "Persistent disks CRUD, and machine-level attach/detach-persistent-disk actions",
        "Physical machine management",
        "Global sessions (CPA cross-pod session list and actions)",
        "Global desktop/application entitlements (CPA)",
        "Config CRUD for authenticators (SAML/RADIUS/GSSAPI/JWT), TrueSSO, roles, permissions",
        "Config CRUD for App Volumes Manager, UEM servers, compute profiles",
        "Connection Server management (enable/disable, certificate import/export)",
        "Log collector actions (initiate collection, generate download URLs, purge bundles)",
        "Capacity providers (AWS WorkSpaces, Azure VMware Solution)",
        "Workspace ONE Assist integration",
        "CEIP/syslog/URL-redirection write operations (resources expose read-only)",
        "Key agreement / smart card login",
        "Virtual Center CRUD — list_virtual_centers is read-only; no way to register, update, "
        "remove a vCenter, or validate its certificate",
        "Gateway CRUD — list_gateways is read-only; no way to register, update, remove a UAG, "
        "or manage its certificate",
        "Instant clone domain account CRUD — list_ic_domain_accounts is read-only; no create/"
        "delete, and ad_sites sub-resource is not exposed",
        "License actions (e.g. reset-named-user-metrics)",
        "Image management assets (im-assets) — separate resource type from the streams/"
        "versions/tags covered by list_image_management, not covered at all",
        "Agent/server installer package management, application icons, category folders",
        "Per-pool policy overrides (desktop-pools/{id}/policies and .../policies/overrides)",
        "Manual desktop pool machine membership (add/remove machines by ID or name)",
        "Desktop pool provisioning task tracking (list/cancel/pause/resume push-image tasks)",
        "Machine alias assignment (assign/unassign-aliases) and agent-upgrade scheduling "
        "(schedule/cancel-agent-upgrade, agent-upgrade-tasks)",
    ],
}


def register(mcp: FastMCP) -> None:

    @mcp.tool(annotations=READ_ONLY)
    async def get_api_coverage() -> dict:
        """List all available Horizon MCP tools, resources, and unsupported operations.

        Call this to understand what can be managed via this MCP server before attempting
        a task, or to accurately inform users which Horizon features are and are not supported.

        Returns three sections:
          tools     — all callable tools grouped by function
          resources — read-only MCP Resources (horizon://<path>) for config and monitor data
          not_yet_supported — Horizon API operations not yet implemented
        """
        return _COVERAGE
