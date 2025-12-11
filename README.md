# OpenShift MCP Server

A Model Context Protocol (MCP) server for OpenShift diagnostics and troubleshooting.

## Features

- **Storage Analysis**: `get_storage_usage` - comprehensive report of ephemeral storage usage on nodes, including top pod consumers.

## Installation

```bash
# Using uv (recommended)
uv tool install .

# Or pip
pip install .
```

## Configuration

This server relies on the `oc` command line tool.
1. Ensure `oc` is installed and in your PATH.
2. Ensure you are authenticated (`oc login ...`) to your target cluster before running the server.

### MCP Client Configuration

Configure the MCP server in your Claude Desktop or Gemini CLI settings:

```json
{
  "mcpServers": {
    "openshift-tools": {
      "command": "uv",
      "args": ["run", "openshift-mcp-server"]
    }
  }
}
```

## Example Usage

Once configured, you can ask questions like:
> "Check storage usage for node worker-0"

**Simulated Tool Output:**

```markdown
### Node: worker-0
- **Filesystem**: Used: 85.20 Gi | Capacity: 100.00 Gi | Available: 14.80 Gi
- **Image FS**: Used: 25.50 Gi
- **Total Pod Ephemeral Storage**: 10.20 Gi

**Top Pod Consumers:**
- 3.10 Gi: `openshift-monitoring/prometheus-k8s-0`
- 2.50 Gi: `my-project/data-processor-7d9b8c-x9z2`
- 1.20 Gi: `logging/fluentd-abc12`
```

## Development

```bash
# Run locally
uv run openshift-mcp-server
```

### Testing the server directly

When run directly, the server expects JSON-RPC messages on standard input. You can test its basic functionality by piping an `initialize` message:

```bash
echo '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1.0"}}}' | uv run openshift-mcp-server
```

Expected output:
```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"subscribe":false,"listChanged":false},"tools":{"listChanged":false}},"serverInfo":{"name":"OpenShift Tools","version":"0.1.0"}}}
```
