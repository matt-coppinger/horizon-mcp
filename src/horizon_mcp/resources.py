"""MCP Resources: read-only Horizon config and monitor data.

Resources are exposed to the AI as context without consuming tool slots.
All resources return JSON-formatted data from the Horizon REST API.
Use get_api_coverage (tool) to list all available resource URIs.
"""
import json

from fastmcp import FastMCP

from .client import api_get


def register(mcp: FastMCP) -> None:

    # ── Config: RBAC ───────────────────────────────────────────────────────────

    @mcp.resource("horizon://config/roles")
    async def config_roles() -> str:
        """RBAC roles defined in Horizon (name, id, privileges)."""
        return json.dumps(await api_get("/config/v1/roles") or [])

    @mcp.resource("horizon://config/permissions")
    async def config_permissions() -> str:
        """Permission assignments mapping roles to access groups and principals."""
        return json.dumps(await api_get("/config/v1/permissions") or [])

    @mcp.resource("horizon://config/privileges")
    async def config_privileges() -> str:
        """All selectable Horizon admin privileges."""
        return json.dumps(await api_get("/config/v1/privileges") or [])

    @mcp.resource("horizon://config/local-access-groups")
    async def config_local_access_groups() -> str:
        """Local access groups used for role-based admin delegation."""
        return json.dumps(await api_get("/config/v1/local-access-groups") or [])

    @mcp.resource("horizon://config/federation-access-groups")
    async def config_federation_access_groups() -> str:
        """Federation access groups (Cloud Pod Architecture)."""
        return json.dumps(await api_get("/config/v1/federation-access-groups") or [])

    @mcp.resource("horizon://config/gateway-access-users-or-groups")
    async def config_gateway_access() -> str:
        """Users and groups with gateway access."""
        return json.dumps(await api_get("/config/v1/gateway-access-users-or-groups") or [])

    @mcp.resource("horizon://config/users-or-groups-global-summary")
    async def config_users_groups_global_summary() -> str:
        """Global summary of admin users and groups across pods."""
        return json.dumps(await api_get("/config/v1/users-or-groups-global-summary") or [])

    # ── Config: Authenticators ─────────────────────────────────────────────────

    @mcp.resource("horizon://config/saml-authenticators")
    async def config_saml_authenticators() -> str:
        """SAML 2.0 authenticators configured in Horizon."""
        return json.dumps(await api_get("/config/v1/saml-authenticators") or [])

    @mcp.resource("horizon://config/radius-authenticators")
    async def config_radius_authenticators() -> str:
        """RADIUS authenticators configured in Horizon."""
        return json.dumps(await api_get("/config/v1/radius-authenticators") or [])

    @mcp.resource("horizon://config/gssapi-authenticators")
    async def config_gssapi_authenticators() -> str:
        """GSSAPI/Kerberos authenticators configured in Horizon."""
        return json.dumps(await api_get("/config/v1/gssapi-authenticators") or [])

    @mcp.resource("horizon://config/jwt-authenticators")
    async def config_jwt_authenticators() -> str:
        """JWT authenticators configured in Horizon."""
        return json.dumps(await api_get("/config/v1/jwt-authenticators") or [])

    @mcp.resource("horizon://config/unauthenticated-access-users")
    async def config_unauthenticated_access_users() -> str:
        """Users configured for unauthenticated (kiosk) access."""
        return json.dumps(await api_get("/config/v1/unauthenticated-access-users") or [])

    # ── Config: App Volumes & UEM ──────────────────────────────────────────────

    @mcp.resource("horizon://config/app-volumes-managers")
    async def config_app_volumes_managers() -> str:
        """App Volumes Managers registered with Horizon (id, URL, status)."""
        return json.dumps(await api_get("/config/v1/app-volumes-manager") or [])

    @mcp.resource("horizon://config/uem-servers")
    async def config_uem_servers() -> str:
        """User Environment Manager servers registered with Horizon."""
        return json.dumps(await api_get("/config/v1/uem-servers") or [])

    # ── Config: TrueSSO ────────────────────────────────────────────────────────

    @mcp.resource("horizon://config/true-sso")
    async def config_true_sso() -> str:
        """TrueSSO connector configurations."""
        return json.dumps(await api_get("/config/v1/true-sso") or [])

    @mcp.resource("horizon://config/true-sso-enrollment-servers")
    async def config_true_sso_enrollment_servers() -> str:
        """TrueSSO enrollment servers."""
        return json.dumps(await api_get("/config/v1/true-sso-enrollment-servers") or [])

    # ── Config: Infrastructure ─────────────────────────────────────────────────

    @mcp.resource("horizon://config/compute-profiles")
    async def config_compute_profiles() -> str:
        """Compute profiles available for pool and farm provisioning."""
        return json.dumps(await api_get("/config/v1/compute-profiles") or [])

    @mcp.resource("horizon://config/customization-specifications")
    async def config_customization_specifications() -> str:
        """vCenter customization specifications (Sysprep/QuickPrep) defined in config."""
        return json.dumps(await api_get("/config/v1/customization-specifications") or [])

    @mcp.resource("horizon://config/external-deployments")
    async def config_external_deployments() -> str:
        """External deployments (e.g. Horizon Cloud links) registered with this pod."""
        return json.dumps(await api_get("/config/v1/external-deployments") or [])

    @mcp.resource("horizon://config/secondary-credentials")
    async def config_secondary_credentials() -> str:
        """Secondary credentials configured for connection servers."""
        return json.dumps(await api_get("/config/v1/secondary-credentials") or [])

    @mcp.resource("horizon://config/message-clients")
    async def config_message_clients() -> str:
        """Message security mode clients registered with Horizon."""
        return json.dumps(await api_get("/config/v1/message-clients") or [])

    @mcp.resource("horizon://config/rcx-servers")
    async def config_rcx_servers() -> str:
        """RCX (Remote Console) servers registered with Horizon."""
        return json.dumps(await api_get("/config/v1/rcx/servers") or [])

    # ── Config: Settings ───────────────────────────────────────────────────────

    @mcp.resource("horizon://config/settings/agent-restriction")
    async def config_settings_agent_restriction() -> str:
        """Agent restriction settings (allowed client versions and types)."""
        return json.dumps(await api_get("/config/v1/settings/agent-restriction-settings") or {})

    @mcp.resource("horizon://config/settings/client")
    async def config_settings_client() -> str:
        """Client feature and behaviour settings."""
        return json.dumps(await api_get("/config/v1/settings/client-settings") or {})

    @mcp.resource("horizon://config/settings/feature")
    async def config_settings_feature() -> str:
        """Feature toggle settings."""
        return json.dumps(await api_get("/config/v1/settings/feature") or {})

    @mcp.resource("horizon://config/settings/general")
    async def config_settings_general() -> str:
        """General Horizon settings."""
        return json.dumps(await api_get("/config/v1/settings/general") or {})

    @mcp.resource("horizon://config/settings/security")
    async def config_settings_security() -> str:
        """Security-related Horizon settings."""
        return json.dumps(await api_get("/config/v1/settings/security") or {})

    @mcp.resource("horizon://config/pre-logon-settings")
    async def config_pre_logon_settings() -> str:
        """Pre-logon message and warning banner settings."""
        return json.dumps(await api_get("/config/v1/pre-logon-settings") or {})

    @mcp.resource("horizon://config/syslog")
    async def config_syslog() -> str:
        """Syslog server configuration."""
        return json.dumps(await api_get("/config/v1/syslog") or {})

    @mcp.resource("horizon://config/ceip")
    async def config_ceip() -> str:
        """Customer Experience Improvement Program (CEIP) enrollment status."""
        return json.dumps(await api_get("/config/v1/ceip") or {})

    @mcp.resource("horizon://config/url-redirection")
    async def config_url_redirection() -> str:
        """URL content redirection rules."""
        return json.dumps(await api_get("/config/v1/url-redirection") or [])

    @mcp.resource("horizon://config/log-collector/log-levels")
    async def config_log_levels() -> str:
        """Current log level settings for Horizon components."""
        return json.dumps(await api_get("/config/v1/log-collector/log-levels") or {})

    @mcp.resource("horizon://config/log-collector/tasks")
    async def config_log_collector_tasks() -> str:
        """Log collection tasks (in-progress and completed bundles)."""
        return json.dumps(await api_get("/config/v1/log-collector/tasks") or [])

    # ── Monitor ────────────────────────────────────────────────────────────────

    @mcp.resource("horizon://monitor/app-volumes-managers")
    async def monitor_app_volumes_managers() -> str:
        """App Volumes Manager health and connectivity status."""
        return json.dumps(await api_get("/monitor/v2/app-volumes-managers") or [])

    @mcp.resource("horizon://monitor/event-database")
    async def monitor_event_database() -> str:
        """Event database connection status and metrics."""
        return json.dumps(await api_get("/monitor/v2/event-database") or {})

    @mcp.resource("horizon://monitor/rds-servers")
    async def monitor_rds_servers() -> str:
        """Health and session load for all RDS servers across all farms."""
        return json.dumps(await api_get("/monitor/v4/rds-servers") or [])

    @mcp.resource("horizon://monitor/saml-authenticators")
    async def monitor_saml_authenticators() -> str:
        """SAML authenticator health and certificate status."""
        return json.dumps(await api_get("/monitor/v4/saml-authenticators") or [])

    @mcp.resource("horizon://monitor/true-sso")
    async def monitor_true_sso() -> str:
        """TrueSSO connector health and certificate status."""
        return json.dumps(await api_get("/monitor/v1/true-sso") or [])

    @mcp.resource("horizon://monitor/datastores/usage-metrics")
    async def monitor_datastore_usage() -> str:
        """Datastore space usage metrics broken down by pool and farm."""
        return json.dumps(await api_get("/monitor/v1/datastores/usage-metrics") or [])

    @mcp.resource("horizon://monitor/pods")
    async def monitor_pods() -> str:
        """Remote pod health in Cloud Pod Architecture (CPA) federation."""
        return json.dumps(await api_get("/monitor/v1/pods") or [])

    @mcp.resource("horizon://monitor/pods/global-session-metrics")
    async def monitor_global_session_metrics() -> str:
        """Aggregate session counts across all pods in CPA federation."""
        return json.dumps(await api_get("/monitor/v1/pods/global-session-metrics") or {})

    @mcp.resource("horizon://monitor/message-clients")
    async def monitor_message_clients() -> str:
        """Message security client health status."""
        return json.dumps(await api_get("/monitor/v1/message-clients") or [])
