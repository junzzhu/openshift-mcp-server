from openshift_mcp_server.utils.oc import run_oc_command, run_command, OCError
import urllib.parse
import json
import logging
import asyncio

logger = logging.getLogger("openshift-mcp-server")

PROMETHEUS_ENDPOINT = "/api/v1/namespaces/openshift-monitoring/services/https:prometheus-k8s:9091/proxy/api/v1/query"

# Cache for Prometheus route URL
_prometheus_route_cache = None

async def _get_prometheus_route() -> str:
    """
    Get the Prometheus route URL. Uses caching to avoid repeated lookups.
    
    Returns:
        The Prometheus route host URL, or None if route doesn't exist.
    """
    global _prometheus_route_cache
    
    if _prometheus_route_cache is not None:
        return _prometheus_route_cache
    
    try:
        # Try to get the prometheus-k8s route
        stdout = await run_oc_command([
            "get", "route", "prometheus-k8s",
            "-n", "openshift-monitoring",
            "-o", "jsonpath={.spec.host}"
        ])
        
        if stdout and stdout.strip():
            _prometheus_route_cache = stdout.strip()
            logger.info(f"Using Prometheus route: {_prometheus_route_cache}")
            return _prometheus_route_cache
        
        logger.warning("Prometheus route exists but has no host")
        return None
        
    except OCError as e:
        logger.info(f"Prometheus route not found, will use proxy endpoint: {e}")
        return None

async def query_prometheus(query: str, endpoint: str = PROMETHEUS_ENDPOINT) -> dict:
    """
    Execute a PromQL query against the OpenShift Prometheus instance.
    
    Tries to use the Prometheus route first (if available), falls back to proxy endpoint.
    
    Args:
        query: The PromQL query string.
        endpoint: The API endpoint (default: openshift-monitoring proxy, used as fallback).
        
    Returns:
        parsed JSON response from Prometheus.
    """
    # Try to get the route URL first
    route_host = await _get_prometheus_route()
    
    if route_host:
        # Use route-based access with curl
        try:
            return await _query_via_route(query, route_host)
        except OCError as e:
            logger.warning(f"Route-based query failed, falling back to proxy: {e}")
            # Fall through to proxy method
    
    # Fallback to proxy endpoint
    params = urllib.parse.urlencode({"query": query})
    full_url = f"{endpoint}?{params}"
    
    try:
        stdout = await run_oc_command(["get", "--raw", full_url])
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Prometheus response: {e}")
        raise OCError(f"Invalid JSON from Prometheus: {e}")
    except OCError as e:
        logger.error(f"Prometheus query failed: {e}")
        raise

async def _query_via_route(query: str, route_host: str) -> dict:
    """
    Query Prometheus via route using curl with bearer token.
    
    Args:
        query: The PromQL query string.
        route_host: The Prometheus route hostname.
        
    Returns:
        parsed JSON response from Prometheus.
    """
    # Get the bearer token
    token = await run_oc_command(["whoami", "-t"])
    token = token.strip()
    
    # URL encode the query
    encoded_query = urllib.parse.quote(query)
    url = f"https://{route_host}/api/v1/query?query={encoded_query}"
    
    # Use curl to query with bearer token
    curl_cmd = [
        "curl", "-k", "-s",
        "-H", f"Authorization: Bearer {token}",
        url
    ]
    
    try:
        stdout = await run_command(curl_cmd)
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Prometheus response from route: {e}")
        raise OCError(f"Invalid JSON from Prometheus route: {e}")

async def check_prometheus_availability() -> bool:
    """Check if Prometheus endpoint is reachable."""
    try:
        # Simple query to check upness, e.g. up
        await query_prometheus("up")
        return True
    except OCError:
        return False
