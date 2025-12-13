from mcp.server.fastmcp import FastMCP
from openshift_mcp_server.tools.storage import get_cluster_storage_report, inspect_node_storage_forensics, check_persistent_volume_capacity
from openshift_mcp_server.tools.resources import get_cluster_resource_balance
from openshift_mcp_server.tools.monitoring import detect_pod_restarts_anomalies, get_gpu_utilization

# Initialize the FastMCP server
mcp = FastMCP("OpenShift Tools")

# Register tools
mcp.tool()(get_cluster_storage_report)
mcp.tool()(inspect_node_storage_forensics)
mcp.tool()(check_persistent_volume_capacity)
mcp.tool()(get_cluster_resource_balance)
mcp.tool()(detect_pod_restarts_anomalies)
mcp.tool()(get_gpu_utilization)

def main():
    """Main entry point for the server."""
    mcp.run()

if __name__ == "__main__":
    main()
