"""Monitor tools: health metrics, connection servers, gateways, sessions."""
from typing import Annotated

from fastmcp import FastMCP

from ..client import api_get


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_health_metrics() -> dict:
        """Get an overall health summary for all Horizon components.

        Returns health status for connection servers, virtual centers, gateways,
        AD domains, SAML authenticators, and other infrastructure components.
        """
        return await api_get("/monitor/v1/health-metrics")

    @mcp.tool()
    async def list_connection_servers_health() -> list:
        """List health and status information for all Horizon Connection Servers."""
        return await api_get("/monitor/v4/connection-servers") or []

    @mcp.tool()
    async def get_connection_server_health(
        server_id: Annotated[str, "Connection server ID"],
    ) -> dict:
        """Get detailed health information for a specific Connection Server."""
        return await api_get(f"/monitor/v4/connection-servers/{server_id}")

    @mcp.tool()
    async def list_desktop_pool_metrics() -> list:
        """List session and machine count metrics for all desktop pools.

        Returns counts of connected, disconnected, and available machines per pool.
        """
        return await api_get("/monitor/v3/desktop-pools/metrics") or []

    @mcp.tool()
    async def get_session_metrics() -> dict:
        """Get a summary of current session counts (connected, disconnected, pending)."""
        return await api_get("/monitor/v1/sessions/metrics")

    @mcp.tool()
    async def list_gateway_health() -> list:
        """List health and connectivity status for all registered Unified Access Gateways."""
        return await api_get("/monitor/v5/gateways") or []

    @mcp.tool()
    async def list_virtual_center_health() -> list:
        """List connectivity and health status for all configured vCenter Servers."""
        return await api_get("/monitor/v4/virtual-centers") or []

    @mcp.tool()
    async def list_ad_domain_health() -> list:
        """List reachability and authentication status for all Active Directory domains."""
        return await api_get("/monitor/v4/ad-domains") or []

    @mcp.tool()
    async def get_machine_count_metrics() -> dict:
        """Get aggregate machine state counts across all desktop pools.

        Returns totals for AVAILABLE, CONNECTED, DISCONNECTED, MAINTENANCE,
        ERROR, and other machine states.
        """
        return await api_get("/monitor/v2/machines/count-metrics")

    @mcp.tool()
    async def get_system_metrics() -> dict:
        """Get system-level performance metrics for all Horizon components.

        Returns CPU, memory, and other system metrics for connection servers
        and infrastructure components.
        """
        return await api_get("/monitor/v2/system-metrics")

    @mcp.tool()
    async def list_farm_health() -> list:
        """List health and capacity metrics for all RDS farms."""
        return await api_get("/monitor/v2/farms") or []

    @mcp.tool()
    async def get_license_usage_metrics() -> dict:
        """Get current and highest historical usage metrics for the Horizon license."""
        return await api_get("/monitor/v1/licenses/usage-metrics")

    @mcp.tool()
    async def get_rds_server_count_metrics() -> dict:
        """Get aggregate RDS server state counts across all farms."""
        return await api_get("/monitor/v1/rds-servers/count-metrics")
