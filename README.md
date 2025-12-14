# OpenShift MCP Server

A Model Context Protocol (MCP) server for OpenShift diagnostics and troubleshooting.

## Features

### Storage Tools
- **Storage Analysis**: `get_cluster_storage_report` - comprehensive report of ephemeral storage usage on nodes, including top pod consumers.
- **Deep Forensics**: `inspect_node_storage_forensics` - deep analysis of disk usage on a specific node, checking for unused images and container writable layers.
- **PV Capacity**: `check_persistent_volume_capacity` - monitor persistent volume usage across namespaces with configurable thresholds.

### Monitoring Tools
- **Resource Balance**: `get_cluster_resource_balance` - analyze CPU and memory resource distribution across nodes.
- **Pod Restarts**: `detect_pod_restarts_anomalies` - identify pods with excessive restart counts within a time window.
- **GPU Utilization**: `get_gpu_utilization` - track GPU usage and identify idle GPU resources.

*All monitoring tools use Prometheus metrics via OpenShift route for real-time cluster observability.*

### Pod Diagnostics Tools
- **Pod Logs**: `get_pod_logs` - retrieve and analyze logs from a specific pod, with support for previous container logs, tail limits, and time-based filtering.
- **Pod Diagnostics**: `get_pod_diagnostics` - comprehensive health check of a pod including status, conditions, container states, restart counts, and issue detection.

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
> "Check GPU utilization in the cluster"
>
> "Diagnose pod health for my-app-pod in production namespace"

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

**Simulated Tool Output (`get_gpu_utilization`):**

```markdown
### GPU Utilization Report
**Total GPUs Found:** 4

| Node | GPU | Utilization | Memory Used | Status |
|------|-----|-------------|-------------|--------|
| `host-a:9400` | 0 | **0.0%** | 0.0% | ⚠️ Idle |
| `host-a:9400` | 1 | **85.2%** | 92.3% | ✅ Active |
```

**Simulated Tool Output (`detect_pod_restarts_anomalies`):**

```markdown
### Pod Restart Anomalies (>5 in last 1h)
| Namespace | Pod | Restarts |
|-----------|-----|----------|
| `ns-1` | `pod-a-7b666bd598-cvrlk` | **34** |
| `ns-2` | `pod-b-6dcf7d7bb8-dw8sg` | **16** |

#### 📋 Recommendations
1. **Check Logs**: `oc logs <pod> -n <namespace> --previous`
2. **Check Events**: `oc get events -n <namespace>`
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
{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"get_cluster_storage_report",...},{"name":"inspect_node_storage_forensics",...},...]}}
```
