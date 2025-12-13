from openshift_mcp_server.utils.oc import run_oc_json, run_oc_command, OCError
from openshift_mcp_server.utils.formatting import parse_quantity, format_bytes, format_cpu
import logging
import asyncio

logger = logging.getLogger("openshift-mcp-server")

async def get_cluster_resource_balance() -> str:
    """
    Analyze cluster resource balance, focusing on Request vs Usage gaps.
    
    Why Essential:
    - Scheduling bottleneck diagnosis: Explains why pods are Pending despite capacity.
    - Resource fragmentation detection: Identifies "request vs usage" gaps.
    - Cost efficiency: Reveals over-provisioned nodes.
    
    Returns:
        Markdown table showing CPU/Memory Requests vs Usage per node.
    """
    try:
        # 1. Fetch Node Capacity (Allocatable)
        nodes_task = run_oc_json(["get", "nodes"])
        
        # 2. Fetch All Pods (to sum Requests)
        # We need all pods to calculate total requests per node
        pods_task = run_oc_json(["get", "pods", "--all-namespaces"])
        
        # 3. Fetch Node Usage (Actual Usage from Metrics API)
        # Allow this to fail gracefully if metrics-server is not installed
        usage_task = run_oc_command(["adm", "top", "nodes", "--no-headers"])
        
        # Run in parallel
        nodes_json, pods_json, usage_output = await asyncio.gather(
            nodes_task, 
            pods_task, 
            usage_task, 
            return_exceptions=True
        )
        
        if isinstance(nodes_json, Exception):
            raise nodes_json
            
        nodes = nodes_json.get("items", [])
        node_stats = {}
        
        # Initialize stats with Allocatable Capacity
        for node in nodes:
            name = node["metadata"]["name"]
            allocatable = node["status"]["allocatable"]
            node_stats[name] = {
                "cpu_cap": parse_quantity(allocatable.get("cpu", "0")),
                "mem_cap": parse_quantity(allocatable.get("memory", "0")),
                "pod_cap": parse_quantity(allocatable.get("pods", "0")),
                "cpu_req": 0.0,
                "mem_req": 0.0,
                "pod_count": 0,
                "cpu_used": 0.0,
                "mem_used": 0.0
            }
            
        # Sum up Pod Requests
        if not isinstance(pods_json, Exception):
            for pod in pods_json.get("items", []):
                spec = pod.get("spec", {})
                node_name = spec.get("nodeName")
                status_phase = pod.get("status", {}).get("phase")
                
                # Succeeded/Failed pods don't satisfy resources? 
                # Actually finished pods might release resources, but let's count Running/Pending/Unknown
                # Generally we only care about pods that are occupying space.
                # 'Succeeded' and 'Failed' pods generally don't hold resource text_requests.
                if status_phase in ["Succeeded", "Failed"]:
                    continue
                    
                if node_name and node_name in node_stats:
                    node_stats[node_name]["pod_count"] += 1
                    
                    for container in spec.get("containers", []):
                        requests = container.get("resources", {}).get("requests", {})
                        node_stats[node_name]["cpu_req"] += parse_quantity(requests.get("cpu", "0"))
                        node_stats[node_name]["mem_req"] += parse_quantity(requests.get("memory", "0"))
        else:
            logger.warning(f"Could not fetch pods: {pods_json}")

        # Parse Usage
        metrics_available = False
        if not isinstance(usage_output, Exception) and usage_output:
            metrics_available = True
            for line in usage_output.strip().splitlines():
                parts = line.split()
                if len(parts) >= 5:
                    # Output: NAME CPU(cores) CPU% MEMORY(bytes) MEMORY%
                    name = parts[0]
                    cpu_used_str = parts[1] # e.g. 500m
                    mem_used_str = parts[3] # e.g. 1000Mi
                    
                    if name in node_stats:
                        node_stats[name]["cpu_used"] = parse_quantity(cpu_used_str)
                        node_stats[name]["mem_used"] = parse_quantity(mem_used_str)

        # Format Output
        output = ["### Cluster Resource Balance Report"]
        
        if not metrics_available:
             output.append("> ⚠️  Metrics API not available (oc adm top nodes failed). usage columns will be empty.")
        
        # Table Header
        output.append("| Node | CPU Req | CPU Used | Mem Req | Mem Used | Pods |")
        output.append("|------|---------|----------|---------|----------|------|")
        
        for name, stats in sorted(node_stats.items()):
            # CPU
            cpu_cap = stats['cpu_cap'] or 1.0 # avoid div by zero
            cpu_req_pct = (stats['cpu_req'] / cpu_cap) * 100
            cpu_used_pct = (stats['cpu_used'] / cpu_cap) * 100
            
            # Mem
            mem_cap = stats['mem_cap'] or 1.0
            mem_req_pct = (stats['mem_req'] / mem_cap) * 100
            mem_used_pct = (stats['mem_used'] / mem_cap) * 100
            
            # Highlighting High Usage/Requests
            def highlight(val, boundary=85):
                s = f"{val:.0f}%"
                return f"**{s}**" if val >= boundary else s

            row = (
                f"| `{name}` "
                f"| {highlight(cpu_req_pct)} "
                f"| {highlight(cpu_used_pct) if metrics_available else '-'} "
                f"| {highlight(mem_req_pct)} "
                f"| {highlight(mem_used_pct) if metrics_available else '-'} "
                f"| {stats['pod_count']}/{int(stats['pod_cap'])} |"
            )
            output.append(row)
            
        output.append("")
        
        # Recommendations / Insights
        full_req_nodes = [n for n, s in node_stats.items() if (s['cpu_req']/ (s['cpu_cap'] or 1.0) > 0.85) or (s['mem_req']/ (s['mem_cap'] or 1.0) > 0.85)]
        
        if full_req_nodes:
             output.append("#### 💡 Insights")
             output.append(f"- **Scheduling Pressure**: {len(full_req_nodes)} nodes are >85% requested. New pods may fail to schedule.")
             for node in full_req_nodes:
                 stats = node_stats[node]
                 # Calculate fragmentation gap
                 cpu_gap = (stats['cpu_req'] - stats['cpu_used']) / (stats['cpu_cap'] or 1.0) * 100
                 if metrics_available and cpu_gap > 50:
                     output.append(f"  - **{node}**: High fragmentation ({cpu_gap:.0f}% gap between CPU request & usage). Consider lowering requests for workloads on this node.")

        return "\n".join(output)

    except Exception as e:
        return f"Error calculating cluster resource balance: {e}"
