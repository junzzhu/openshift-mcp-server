from mcp.server.fastmcp import FastMCP
from openshift_mcp_server.tools.storage import get_cluster_storage_report, inspect_node_storage_forensics, check_persistent_volume_capacity
from openshift_mcp_server.tools.resources import get_cluster_resource_balance
from openshift_mcp_server.tools.monitoring import detect_pod_restarts_anomalies, get_gpu_utilization, get_vllm_metrics
from openshift_mcp_server.tools.diagnostics import get_pod_logs, get_pod_diagnostics
from openshift_mcp_server.tools.gpu import inspect_gpu_pod, check_gpu_health

# Initialize the FastMCP server
mcp = FastMCP("OpenShift Tools")

# Register tools
mcp.tool()(get_cluster_storage_report)
mcp.tool()(inspect_node_storage_forensics)
mcp.tool()(check_persistent_volume_capacity)
mcp.tool()(get_cluster_resource_balance)
mcp.tool()(detect_pod_restarts_anomalies)
mcp.tool()(get_gpu_utilization)
mcp.tool()(get_pod_logs)
mcp.tool()(get_pod_diagnostics)
mcp.tool()(inspect_gpu_pod)
mcp.tool()(check_gpu_health)
mcp.tool()(get_vllm_metrics)

def main():
    """Main entry point for the server."""
    mcp.run()

if __name__ == "__main__":
    main()
