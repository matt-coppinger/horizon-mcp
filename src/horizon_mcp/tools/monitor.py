"""Monitor tools: infrastructure health and metrics."""
import asyncio
from typing import Annotated, Literal

from fastmcp import FastMCP

from ..client import api_get

_HEALTH_ENDPOINTS: dict[str, str] = {
    "summary": "/monitor/v1/health-metrics",
    "connection_servers": "/monitor/v4/connection-servers",
    "gateways": "/monitor/v5/gateways",
    "virtual_centers": "/monitor/v4/virtual-centers",
    "ad_domains": "/monitor/v4/ad-domains",
    "farms": "/monitor/v2/farms",
}

_METRICS_ENDPOINTS: dict[str, str] = {
    "pools": "/monitor/v3/desktop-pools/metrics",
    "sessions": "/monitor/v1/sessions/metrics",
    "machines": "/monitor/v2/machines/count-metrics",
    "system": "/monitor/v2/system-metrics",
    "rds_servers": "/monitor/v1/rds-servers/count-metrics",
    "license": "/monitor/v1/licenses/usage-metrics",
}

HealthComponent = Literal["summary", "connection_servers", "gateways", "virtual_centers", "ad_domains", "farms"]
MetricScope = Literal["pools", "sessions", "machines", "system", "rds_servers", "license"]


def register(mcp: FastMCP) -> None:

    @mcp.tool()
    async def get_infrastructure_health(
        components: Annotated[
            list[HealthComponent] | None,
            "Components to check: summary, connection_servers, gateways, "
            "virtual_centers, ad_domains, farms. Defaults to all.",
        ] = None,
    ) -> dict:
        """Get health and status across Horizon infrastructure in a single call.

        Components:
        - summary: overall health rollup across all component types
        - connection_servers: per-server reachability, load, and tunnel counts
        - gateways: Unified Access Gateway connectivity status
        - virtual_centers: vCenter Server connectivity and health
        - ad_domains: Active Directory domain reachability and bind status
        - farms: RDS farm health and server capacity

        Results are keyed by component name. A failed component returns its error
        as a string rather than failing the whole call.

        Replaces: get_health_metrics, list_connection_servers_health,
        list_gateway_health, list_virtual_center_health, list_ad_domain_health,
        list_farm_health.
        """
        selected = list(_HEALTH_ENDPOINTS) if components is None else list(components)
        unknown = [c for c in selected if c not in _HEALTH_ENDPOINTS]
        if unknown:
            raise ValueError(
                f"Unknown components: {unknown}. Valid options: {list(_HEALTH_ENDPOINTS)}"
            )
        results = await asyncio.gather(
            *[api_get(_HEALTH_ENDPOINTS[c]) for c in selected],
            return_exceptions=True,
        )
        return {
            c: (str(r) if isinstance(r, Exception) else (r or []))
            for c, r in zip(selected, results)
        }

    @mcp.tool()
    async def get_connection_server_health(
        server_id: Annotated[str, "Connection server ID"],
    ) -> dict:
        """Get detailed health information for a specific Connection Server."""
        return await api_get(f"/monitor/v4/connection-servers/{server_id}")

    @mcp.tool()
    async def get_metrics(
        scope: Annotated[
            list[MetricScope] | None,
            "Metric scopes to retrieve: pools, sessions, machines, system, "
            "rds_servers, license. Defaults to all.",
        ] = None,
    ) -> dict:
        """Get performance and capacity metrics across the Horizon environment in a single call.

        Scopes:
        - pools: session and machine counts per desktop pool
        - sessions: aggregate connected/disconnected/pending session totals
        - machines: aggregate machine state counts across all pools
        - system: CPU and memory metrics for connection servers
        - rds_servers: RDS server state counts across all farms
        - license: current and peak license usage

        Results are keyed by scope name. A failed scope returns its error as a string
        rather than failing the whole call.

        Replaces: list_desktop_pool_metrics, get_session_metrics,
        get_machine_count_metrics, get_system_metrics, get_rds_server_count_metrics,
        get_license_usage_metrics.
        """
        selected = list(_METRICS_ENDPOINTS) if scope is None else list(scope)
        unknown = [s for s in selected if s not in _METRICS_ENDPOINTS]
        if unknown:
            raise ValueError(
                f"Unknown scopes: {unknown}. Valid options: {list(_METRICS_ENDPOINTS)}"
            )
        results = await asyncio.gather(
            *[api_get(_METRICS_ENDPOINTS[s]) for s in selected],
            return_exceptions=True,
        )
        return {
            s: (str(r) if isinstance(r, Exception) else (r or {}))
            for s, r in zip(selected, results)
        }
