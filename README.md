# OpenShift MCP Server

A Model Context Protocol (MCP) server for OpenShift diagnostics and troubleshooting.

## Features

- **Storage Analysis**: `get_cluster_storage_report` - comprehensive report of ephemeral storage usage on nodes, including top pod consumers.
- **Deep Forensics**: `inspect_node_storage_forensics` - deep analysis of disk usage on a specific node, checking for unused images and container writable layers.

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
> "Give me a summary of storage usage for all nodes"
> 
> "Why is node worker9 running out of space?"

**Simulated Tool Output (`get_cluster_storage_report`):**

```markdown
# Storage Usage Report (3 nodes)

### Node: master0.example.com
- **Filesystem**: Used: 36.70 Gi | Capacity: 99.44 Gi | Available: 62.74 Gi
- **Image FS**: Used: 34.17 Gi
- **Total Pod Ephemeral Storage**: 5.19 Gi

**Top Pod Consumers:**
- 2.60 Gi: `openshift-marketplace/redhat-operators-gb8ff`
- 974.96 Mi: `openshift-marketplace/community-operators-fq744`
```

**Simulated Tool Output (`inspect_node_storage_forensics`):**

```markdown
### Forensic Report: worker9.example.com

**Physical Disk (Container Storage):**
Filesystem      Size  Used Avail Use% Mounted on
/dev/vda4       250G  206G   44G  83% /var/lib/containers

**Reclaimable Space (Unused Images):** 249.42 Gi
-> **Recommendation**: Run `oc adm prune images` to recover this space.

**Top Pod Writable Layers (Container Drift):**
- 1.99 Gi: `nvidia-gpu-operator/nvidia-driver-daemonset-416.94.202508261955-0-t9d77`
- 54.95 Mi: `nvidia-gpu-operator/nvidia-dcgm-exporter-cbkc6`
```

## Development

```bash
# Run locally
uv run openshift-mcp-server
```

### Testing the server directly

When run directly, the server expects JSON-RPC messages on standard input. You can verify the registered tools by simulating a full client handshake (Initialize -> Initialized -> Tools/List):

```bash
(echo '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1.0"}}}'; sleep 0.5; echo '{"jsonrpc": "2.0", "method": "notifications/initialized"}'; sleep 0.5; echo '{"jsonrpc": "2.0", "id": 2, "method": "tools/list"}') | uv run openshift-mcp-server
```

Expected output (truncated for brevity):
```json
{"jsonrpc":"2.0","id":1,"result":{...}}
{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"get_cluster_storage_report",...},{"name":"inspect_node_storage_forensics",...}]}}
```
