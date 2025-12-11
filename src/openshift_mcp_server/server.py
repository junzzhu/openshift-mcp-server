from mcp.server.fastmcp import FastMCP
from openshift_mcp_server.tools.storage import get_cluster_storage_report, inspect_node_storage_forensics

# Initialize the FastMCP server
mcp = FastMCP("OpenShift Tools")

# Register tools
mcp.tool()(get_cluster_storage_report)
mcp.tool()(inspect_node_storage_forensics)

def main():
    """Main entry point for the server."""
    mcp.run()

if __name__ == "__main__":
    main()
