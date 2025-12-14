from openshift_mcp_server.utils.prometheus import query_prometheus, OCError
import logging

logger = logging.getLogger("openshift-mcp-server")

async def detect_pod_restarts_anomalies(threshold: int = 5, duration: str = "1h") -> str:
    """
    Identify unstable pods experiencing high restart rates.
    
    Why:
    - Application stability indicator: High restart rates signal code issues (OOM, panics, misconfigurations)
    - Proactive detection: Catches intermittent failures before they become incidents
    - Actionable: Directly points to problematic workloads
    
    Args:
        threshold: Minimum number of restarts to flag (default: 5).
        duration: Window of time to analyze (e.g., '1h', '24h', '10m').
        
    Returns:
        Markdown report of unstable pods.
    """
    query = f'sum(increase(kube_pod_container_status_restarts_total[{duration}])) by (namespace, pod) > {threshold}'
    
    try:
        result = await query_prometheus(query)
        
        status = result.get("status")
        if status != "success":
            return f"Prometheus query failed with status: {status}"
            
        data = result.get("data", {})
        result_type = data.get("resultType")
        results = data.get("result", [])
        
        output = [f"### Pod Restart Anomalies (>{threshold} in last {duration})"]
        
        if not results:
             output.append(f"✅ No pods found with >{threshold} restarts in the last {duration}.")
             return "\n".join(output)
             
        # Sort by value (restart count) descending
        # Value format is [timestamp, "value_string"]
        results.sort(key=lambda x: float(x.get("value", [0, "0"])[1]), reverse=True)
        
        output.append("| Namespace | Pod | Restarts |")
        output.append("|-----------|-----|----------|")
        
        for r in results:
            metric = r.get("metric", {})
            value = r.get("value", [0, "0"])[1]
            namespace = metric.get("namespace", "unknown")
            pod = metric.get("pod", "unknown")
            
            restarts = float(value)
            
            output.append(f"| `{namespace}` | `{pod}` | **{restarts:.0f}** |")
            
        output.append("")
        output.append("#### 📋 Recommendations")
        output.append("1. **Check Logs**: `oc logs <pod> -n <namespace> --previous` to see why it crashed.")
        output.append("2. **Check Events**: `oc get events -n <namespace> --field-selector involvedObject.name=<pod>`")
        output.append("3. **OOM Killed?**: Check if memory limit is too low.")
        
        return "\n".join(output)

    except OCError as e:
        return f"Error querying Prometheus: {e}\n\nMake sure OpenShift Monitoring is enabled and you have permission to access the Prometheus API."

async def get_gpu_utilization() -> str:
    """
    Monitor GPU usage and health across the cluster.
    
    Why:
    - Cost efficiency: GPUs are expensive. Low utilization indicates wasted money.
    - Resource optimization: Identifies idle GPUs that could be deallocated.
    - Hardware health: High error rates indicate hardware issues.
    
    Prerequisites:
    - NVIDIA GPU Operator installed (exports DCGM metrics).
    
    Returns:
        Markdown report of GPU utilization per node.
    """
    
    # Query for GPU utilization, memory usage, and framebuffer stats
    # We'll use multiple queries and correlate them
    queries = {
        "utilization": "DCGM_FI_DEV_GPU_UTIL",
        "memory_used": "DCGM_FI_DEV_FB_USED",
        "memory_free": "DCGM_FI_DEV_FB_FREE",
    }
    
    try:
        # Fetch all metrics
        results = {}
        for name, query in queries.items():
            try:
                result = await query_prometheus(query)
                if result.get("status") == "success":
                    results[name] = result.get("data", {}).get("result", [])
                else:
                    results[name] = []
            except OCError:
                results[name] = []
        
        # Check if we got any GPU metrics
        if not any(results.values()):
            return ("### GPU Utilization Report\n\n"
                   "⚠️  No GPU metrics found.\n\n"
                   "**Possible reasons:**\n"
                   "- NVIDIA GPU Operator is not installed\n"
                   "- No GPU nodes in the cluster\n"
                   "- DCGM exporter is not running\n"
                   "- Prometheus is not scraping DCGM metrics")
        
        # Build a map: (node, gpu_index) -> {util, mem_used, mem_free}
        gpu_map = {}
        
        for metric_data in results.get("utilization", []):
            metric = metric_data.get("metric", {})
            node = metric.get("node", metric.get("instance", "unknown"))
            gpu = metric.get("gpu", metric.get("GPU", "0"))
            value = float(metric_data.get("value", [0, "0"])[1])
            
            key = (node, gpu)
            if key not in gpu_map:
                gpu_map[key] = {}
            gpu_map[key]["util"] = value
        
        for metric_data in results.get("memory_used", []):
            metric = metric_data.get("metric", {})
            node = metric.get("node", metric.get("instance", "unknown"))
            gpu = metric.get("gpu", metric.get("GPU", "0"))
            value = float(metric_data.get("value", [0, "0"])[1])
            
            key = (node, gpu)
            if key not in gpu_map:
                gpu_map[key] = {}
            gpu_map[key]["mem_used"] = value
        
        for metric_data in results.get("memory_free", []):
            metric = metric_data.get("metric", {})
            node = metric.get("node", metric.get("instance", "unknown"))
            gpu = metric.get("gpu", metric.get("GPU", "0"))
            value = float(metric_data.get("value", [0, "0"])[1])
            
            key = (node, gpu)
            if key not in gpu_map:
                gpu_map[key] = {}
            gpu_map[key]["mem_free"] = value
        
        if not gpu_map:
            return ("### GPU Utilization Report\n\n"
                   "⚠️  No GPU data available in metrics.")
        
        # Format output
        output = ["### GPU Utilization Report"]
        output.append(f"**Total GPUs Found:** {len(gpu_map)}\n")
        
        # Table
        output.append("| Node | GPU | Utilization | Memory Used | Memory Free | Status |")
        output.append("|------|-----|-------------|-------------|-------------|--------|")
        
        idle_gpus = []
        high_util_gpus = []
        
        for (node, gpu), stats in sorted(gpu_map.items()):
            util = stats.get("util", 0)
            mem_used = stats.get("mem_used", 0)
            mem_free = stats.get("mem_free", 0)
            
            # Calculate memory percentage if we have both used and free
            if mem_used > 0 or mem_free > 0:
                total_mem = mem_used + mem_free
                mem_pct = (mem_used / total_mem * 100) if total_mem > 0 else 0
                mem_str = f"{mem_pct:.1f}%"
            else:
                mem_str = "N/A"
            
            # Determine status
            if util == 0:
                status = "⚠️ Idle"
                idle_gpus.append((node, gpu))
            elif util > 90:
                status = "🔥 High"
                high_util_gpus.append((node, gpu, util))
            else:
                status = "✅ Active"
            
            output.append(f"| `{node}` | {gpu} | **{util:.1f}%** | {mem_str} | {mem_free:.0f} MiB | {status} |")
        
        output.append("")
        
        # Insights
        if idle_gpus or high_util_gpus:
            output.append("#### 💡 Insights")
            
            if idle_gpus:
                output.append(f"- **{len(idle_gpus)} Idle GPU(s)** detected (0% utilization):")
                for node, gpu in idle_gpus[:5]:  # Show first 5
                    output.append(f"  - `{node}` GPU {gpu}")
                output.append("  - **Action**: Check if pods are actually using the GPU or if they're just requesting it.")
            
            if high_util_gpus:
                output.append(f"- **{len(high_util_gpus)} High-Utilization GPU(s)** (>90%):")
                for node, gpu, util in high_util_gpus[:5]:
                    output.append(f"  - `{node}` GPU {gpu}: {util:.1f}%")
                output.append("  - **Action**: Consider scaling workloads or adding more GPU nodes.")
        else:
            output.append("#### ✅ All GPUs are operating normally")
        
        return "\n".join(output)
    
    except OCError as e:
        return f"Error querying GPU metrics: {e}\n\nMake sure the NVIDIA GPU Operator and DCGM exporter are installed."
