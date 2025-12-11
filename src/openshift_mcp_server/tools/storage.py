from mcp.server.fastmcp import FastMCP, Context
import logging
from openshift_mcp_server.utils.oc import run_oc_json, get_node_stats_summary, run_oc_debug_node, OCError

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

async def inspect_node_storage_forensics(node_name: str) -> str:
    """
    SLOW operation (10s+). Performs a deep forensic analysis of a node's storage.
    
    Use this tool ONLY when:
    1. A specific node is known to be problematic (full disk).
    2. 'get_storage_usage' does not reveal the root cause.
    
    This tool runs a debug pod on the node to calculate:
    - Real disk usage (df -h).
    - Reclaimable space from UNUSED images.
    - Growth of container writable layers (indicating log/file issues inside containers).
    """
    
    # The script to run inside the node
    # It uses jq and crictl to calculate stats locally on the node to minimize data transfer
    script = """
    echo "### Disk Usage (df -h)"
    df -h /var/lib/containers/storage/
    
    echo "---"
    echo "Collecting CRI stats..."
    
    # 1. Get all images
    crictl images --no-trunc -v -o json > /tmp/all_images.json
    
    # 2. Get running containers to find used images
    crictl ps -a --no-trunc -o json > /tmp/all_containers.json
    
    # Extract IDs of used images
    cat /tmp/all_containers.json | jq -r '.containers[] | select(.state!="CONTAINER_EXITED") | .image.image' | sort -u > /tmp/used_image_tags.txt
    
    # Match tags to Image IDs
    # (This is a simplification; a robust script matches digests, but this approximates well for a quick report)
    cat /tmp/used_image_tags.txt | while read tag; do
        jq -r --arg tag "$tag" '.images[] | select(.repoTags[] | contains($tag)) | .id' /tmp/all_images.json
    done | sort -u > /tmp/used_image_ids.txt
    
    # 3. Calculate Unused Images
    # Get all image IDs
    jq -r '.images[] | .id' /tmp/all_images.json | sort -u > /tmp/all_image_ids.txt
    
    # Find unused IDs
    comm -23 /tmp/all_image_ids.txt /tmp/used_image_ids.txt > /tmp/unused_image_ids.txt
    
    # Sum size of unused images
    TOTAL_UNUSED_SIZE=0
    if [ -s /tmp/unused_image_ids.txt ]; then
        # Create a JSON array of unused IDs for simpler filtering
        # We'll just loop through lines for simplicity in bash
        while read id; do
            SIZE=$(jq -r --arg id "$id" '.images[] | select(.id == $id) | .size' /tmp/all_images.json)
            TOTAL_UNUSED_SIZE=$((TOTAL_UNUSED_SIZE + SIZE))
        done < /tmp/unused_image_ids.txt
    fi
    
    echo "UNUSED_BYTES=$TOTAL_UNUSED_SIZE"
    
    # 4. Writable Layers
    echo "---"
    echo "Analyzing Writable Layers (Top 10)..."
    
    # Get pods and their writable layer usage
    # We iterate over running pods
    crictl pods -s Ready -o json | jq -r '.items[] | .id + "|" + .metadata.namespace + "/" + .metadata.name' > /tmp/pods.txt
    
    echo "SIZE_BYTES POD_NAME"
    while read line; do
        POD_ID=$(echo $line | cut -d'|' -f1)
        POD_NAME=$(echo $line | cut -d'|' -f2)
        
        # Sum up writable layer usage for all containers in the pod
        # Note: crictl stats -p POD_ID returns stats for all containers in that pod
        SIZE=$(crictl stats -p "$POD_ID" -o json | jq -r '.stats[] | .writableLayer.usedBytes.value' | awk '{sum = sum + $1} END {print sum}')
        
        if [ ! -z "$SIZE" ] && [ "$SIZE" -gt 0 ]; then
             echo "$SIZE $POD_NAME"
        fi
    done < /tmp/pods.txt | sort -rn | head -n 10
    """

    try:
        output = await run_oc_debug_node(node_name, script)
        
        # Parse the raw output to format it nicely for the LLM
        lines = output.splitlines()
        formatted_output = [f"### Forensic Report: {node_name}"]
        
        # Extract specific sections
        unused_bytes = 0
        writable_layers = []
        df_output = []
        
        parsing_writable = False
        
        for line in lines:
            if "Filesystem" in line or "/var/lib/containers" in line:
                df_output.append(line)
            elif line.startswith("UNUSED_BYTES="):
                try:
                    unused_bytes = int(line.split("=")[1])
                except (IndexError, ValueError):
                    pass
            elif line.startswith("SIZE_BYTES POD_NAME"):
                parsing_writable = True
            elif parsing_writable and line.strip():
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        size = int(parts[0])
                        name = parts[1]
                        writable_layers.append((size, name))
                    except ValueError:
                        pass
                        
        # Construct the final markdown
        formatted_output.append("\n**Physical Disk (Container Storage):**")
        formatted_output.append("```")
        formatted_output.extend(df_output)
        formatted_output.append("```")
        
        formatted_output.append(f"\n**Reclaimable Space (Unused Images):** {format_bytes(unused_bytes)}")
        if unused_bytes > 1024**3: # > 1GB
            formatted_output.append("-> **Recommendation**: Run `oc adm prune images` to recover this space.")
        
        formatted_output.append("\n**Top Pod Writable Layers (Container Drift):**")
        formatted_output.append("_Usage by containers writing to their root filesystem instead of volumes._")
        for size, name in writable_layers:
            formatted_output.append(f"- {format_bytes(size)}: `{name}`")
            
        return "\n".join(formatted_output)

    except OCError as e:
        return f"Error running forensic analysis on node {node_name}: {e}"

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

async def get_cluster_storage_report(node: str | None = None) -> str:
    """
    Use this FIRST. Fast, high-level summary of storage usage for all nodes or a specific node.
    Checks quotas and reported usage from the Kubelet API.
    
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
