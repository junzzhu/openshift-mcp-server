from mcp.server.fastmcp import FastMCP
from openshift_mcp_server.tools.storage import get_storage_usage

# Initialize the FastMCP server
mcp = FastMCP("OpenShift Tools")

# Register tools
mcp.tool()(get_storage_usage)

def main():
    """Main entry point for the server."""
    mcp.run()

if __name__ == "__main__":
    main()
