from mcp.server.fastmcp import FastMCP, Context
import logging
from openshift_mcp_server.utils.oc import run_oc_json, get_node_stats_summary, OCError

logger = logging.getLogger("openshift-mcp-server")

def format_bytes(size: float) -> str:
    """Format bytes to human readable string (e.g. 1.2 Gi)."""
    power = 2**10
    n = size
    power_labels = {0 : '', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    count = 0
    while n > power:
        n /= power
        count += 1
    return f"{n:.2f} {power_labels.get(count, 'Pi')}"

async def analyze_node_storage(node_name: str) -> str:
    """Analyze storage usage for a specific node."""
    try:
        stats = await get_node_stats_summary(node_name)
    except OCError as e:
        return f"Error fetching stats for node {node_name}: {e}"

    output = [f"### Node: {node_name}"]
    
    # Node Filesystem
    node_fs = stats.get("node", {}).get("fs", {})
    if node_fs:
        used = format_bytes(node_fs.get("usedBytes", 0))
        capacity = format_bytes(node_fs.get("capacityBytes", 0))
        available = format_bytes(node_fs.get("availableBytes", 0))
        output.append(f"- **Filesystem**: Used: {used} | Capacity: {capacity} | Available: {available}")
    
    # Image Filesystem
    image_fs = stats.get("node", {}).get("runtime", {}).get("imageFs", {})
    if image_fs:
        used_image = format_bytes(image_fs.get("usedBytes", 0))
        output.append(f"- **Image FS**: Used: {used_image}")

    # Pod Ephemeral Storage
    pods = stats.get("pods", [])
    total_pod_usage = 0
    pod_usage_list = []

    for pod in pods:
        pod_ref = pod.get("podRef", {})
        namespace = pod_ref.get("namespace", "unknown")
        name = pod_ref.get("name", "unknown")
        
        ephemeral_storage = pod.get("ephemeral-storage", {})
        used_bytes = ephemeral_storage.get("usedBytes", 0)
        
        if used_bytes > 0:
            total_pod_usage += used_bytes
            pod_usage_list.append((used_bytes, f"{namespace}/{name}"))

    output.append(f"- **Total Pod Ephemeral Storage**: {format_bytes(total_pod_usage)}")
    
    # Top Consumers
    output.append("\n**Top Pod Consumers:**")
    pod_usage_list.sort(key=lambda x: x[0], reverse=True)
    
    for usage, pod_name in pod_usage_list[:10]:  # Top 10
        output.append(f"- {format_bytes(usage)}: `{pod_name}`")

    return "\n".join(output)

async def get_storage_usage(node: str | None = None) -> str:
    """
    Get ephemeral storage usage statistics for OpenShift nodes.
    
    If 'node' is provided, analyzes only that node.
    If 'node' is not provided, analyzes all worker nodes.
    """
    if node:
        return await analyze_node_storage(node)
    
    # Get all nodes
    try:
        nodes_json = await run_oc_json(["get", "nodes"])
        nodes = nodes_json.get("items", [])
        
        # Filter out master nodes if needed, or just list all. 
        # The original script grep -v NAME filtered header, effectively listing all.
        node_names = [n["metadata"]["name"] for n in nodes]
        
        results = []
        results.append(f"# Storage Usage Report ({len(node_names)} nodes)\n")
        
        for n in node_names:
            results.append(await analyze_node_storage(n))
            results.append("\n---\n")
            
        return "\n".join(results)
        
    except OCError as e:
        return f"Error listing nodes: {e}"
