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

**Storage Questions:**
> "Give me a summary of storage usage for all nodes"
> 
> "Why is node worker9 running out of space?"
>
> "Check persistent volume capacity across all namespaces"

**Monitoring Questions:**
> "Show me the cluster resource balance"
>
> "Which pods are restarting frequently?"
>
> "Check GPU utilization in the cluster"

**Pod Diagnostics Questions:**
> "Get logs for pod vllm-gpu-558997879d-2dbrp in namespace default"
>
> "Diagnose pod health for my-app-pod in production namespace"
>
> "Show me the previous logs for the crashed container"

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


**Simulated Tool Output (`get_pod_logs`):**

```markdown
### Pod Logs: `gpu/vllm-gpu-558997879d-2dbrp`

#### Container: `vllm-gpu` [CURRENT]
*State: Running (Restarts: 0)*

2025-12-13 18:14:02 INFO: Starting vLLM server...
2025-12-13 18:14:05 INFO: Loading model weights...
2025-12-13 18:14:30 INFO: Model loaded successfully
2025-12-13 18:14:31 INFO: Server listening on 0.0.0.0:8000
```

**Simulated Tool Output (`get_pod_diagnostics`):**

```markdown
### Pod Diagnostics: `gpu/vllm-gpu-558997879d-2dbrp`

#### Pod Status
- **Phase**: Running
- **Node**: host-a
- **QoS Class**: BestEffort
- **Start Time**: 2025-12-12T18:13:58Z

**Conditions**:
- ✅ PodReadyToStartContainers: True
- ✅ Initialized: True
- ✅ Ready: True
- ✅ ContainersReady: True
- ✅ PodScheduled: True

#### Container Status
| Container | Restarts | State | Reason | Exit Code | Ready |
|-----------|----------|-------|--------|-----------|-------|
| `vllm-gpu` | **0** | Running | - | - | ✅ |

#### ✅ No issues detected
```
