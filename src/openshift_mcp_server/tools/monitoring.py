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

async def get_vllm_metrics(namespace: str | None = None, pod_filter: str | None = None) -> str:
    """
    Monitor vLLM inference server performance metrics by directly querying pods.
    
    Why:
    - Performance monitoring: Track request latency and throughput
    - Capacity planning: Monitor queue size and running requests
    - Resource optimization: Track GPU cache usage
    - Proactive alerting: Detect performance degradation
    
    Args:
        namespace: Optional namespace filter
        pod_filter: Optional pod name filter (supports partial match)
        
    Returns:
        Markdown report of vLLM metrics
    """
    from openshift_mcp_server.utils.oc import run_oc_json, run_oc_command
    import re
    
    try:
        # Find all pods across namespaces (or specific namespace)
        if namespace:
            pods_data = await run_oc_json(["get", "pods", "-n", namespace])
        else:
            pods_data = await run_oc_json(["get", "pods", "--all-namespaces"])
        
        # Filter for vLLM pods
        vllm_pods = []
        items = pods_data.get("items", [])
        
        for pod in items:
            pod_name = pod.get("metadata", {}).get("name", "")
            pod_ns = pod.get("metadata", {}).get("namespace", "")
            
            # Check if pod name contains "vllm" and matches filter
            if "vllm" in pod_name.lower():
                if pod_filter and pod_filter.lower() not in pod_name.lower():
                    continue
                
                # Check if pod is running
                phase = pod.get("status", {}).get("phase", "")
                if phase == "Running":
                    vllm_pods.append({"name": pod_name, "namespace": pod_ns})
        
        if not vllm_pods:
            return ("### vLLM Metrics Report\n\n"
                   f"⚠️  No running vLLM pods found (namespace: {namespace or 'all'}, filter: {pod_filter or 'none'})\n\n"
                   "**Possible reasons:**\n"
                   "- No vLLM pods are deployed\n"
                   "- Pods are not in Running state\n"
                   "- Pod name filter excluded all pods")
        
        output = ["### vLLM Performance Metrics\n"]
        output.append(f"**Total vLLM Pods Found:** {len(vllm_pods)}\n")
        
        # Collect metrics from each pod
        pod_metrics = {}
        failed_pods = []
        
        for pod_info in vllm_pods:
            pod_name = pod_info["name"]
            pod_ns = pod_info["namespace"]
            pod_key = f"{pod_ns}/{pod_name}"
            
            try:
                # Execute curl command to fetch metrics from pod
                metrics_output = await run_oc_command([
                    "exec", "-n", pod_ns, pod_name, "--",
                    "curl", "-s", "http://localhost:8000/metrics"
                ])
                
                # Parse Prometheus-format metrics
                metrics = {}
                model_name = "unknown"
                
                for line in metrics_output.split("\n"):
                    # Skip comments and empty lines
                    if line.startswith("#") or not line.strip():
                        continue
                    
                    # Parse metric line: metric_name{labels} value
                    # Extract model_name from labels
                    if 'model_name="' in line:
                        match = re.search(r'model_name="([^"]+)"', line)
                        if match:
                            model_name = match.group(1)
                    
                    # Extract specific metrics we care about
                    if line.startswith("vllm:num_requests_running"):
                        match = re.search(r'}\s+([\d.]+)', line)
                        if match:
                            metrics["running_requests"] = float(match.group(1))
                    
                    elif line.startswith("vllm:num_requests_waiting"):
                        match = re.search(r'}\s+([\d.]+)', line)
                        if match:
                            metrics["waiting_requests"] = float(match.group(1))
                    
                    elif line.startswith("vllm:kv_cache_usage_perc"):
                        match = re.search(r'}\s+([\d.]+)', line)
                        if match:
                            metrics["kv_cache_usage"] = float(match.group(1))
                    
                    elif line.startswith("vllm:prompt_tokens_total"):
                        match = re.search(r'}\s+([\d.]+)', line)
                        if match:
                            metrics["prompt_tokens"] = float(match.group(1))
                    
                    elif line.startswith("vllm:generation_tokens_total"):
                        match = re.search(r'}\s+([\d.]+)', line)
                        if match:
                            metrics["generation_tokens"] = float(match.group(1))
                    
                    # Also capture request success metrics
                    elif line.startswith("vllm:request_success_total"):
                        if 'finished_reason="length"' in line:
                            match = re.search(r'}\s+([\d.]+)', line)
                            if match:
                                metrics["success_length"] = float(match.group(1))
                        elif 'finished_reason="stop"' in line:
                            match = re.search(r'}\s+([\d.]+)', line)
                            if match:
                                metrics["success_stop"] = float(match.group(1))
                
                metrics["model"] = model_name
                pod_metrics[pod_key] = metrics
                
            except OCError as e:
                failed_pods.append(f"{pod_key}: {str(e)}")
                logger.warning(f"Failed to fetch metrics from {pod_key}: {e}")
        
        if not pod_metrics:
            error_msg = ["### vLLM Metrics Report\n"]
            error_msg.append(f"❌ Failed to fetch metrics from all {len(vllm_pods)} pod(s)\n")
            if failed_pods:
                error_msg.append("**Errors:**")
                for err in failed_pods:
                    error_msg.append(f"- {err}")
            return "\n".join(error_msg)
        
        # Summary Table
        output.append("| Pod | Model | Waiting | Running | KV Cache | Prompt Tokens | Gen Tokens | Success |")
        output.append("|-----|-------|---------|---------|----------|---------------|------------|---------|")
        
        alerts = []
        
        for pod_key, metrics in sorted(pod_metrics.items()):
            model = metrics.get("model", "unknown")
            waiting = metrics.get("waiting_requests", 0)
            running = metrics.get("running_requests", 0)
            kv_cache = metrics.get("kv_cache_usage", 0)
            prompt_tokens = metrics.get("prompt_tokens", 0)
            gen_tokens = metrics.get("generation_tokens", 0)
            success_total = metrics.get("success_stop", 0) + metrics.get("success_length", 0)
            
            # Format values
            waiting_str = f"**{int(waiting)}**" if waiting > 10 else f"{int(waiting)}"
            kv_cache_str = f"**{kv_cache*100:.1f}%**" if kv_cache > 0.90 else f"{kv_cache*100:.1f}%"
            
            output.append(f"| `{pod_key}` | `{model}` | {waiting_str} | {int(running)} | {kv_cache_str} | {int(prompt_tokens)} | {int(gen_tokens)} | {int(success_total)} |")
            
            # Generate alerts
            if waiting > 20:
                alerts.append(f"- ⚠️ **{pod_key}**: High queue size ({int(waiting)} waiting). Consider scaling up.")
            if kv_cache > 0.95:
                alerts.append(f"- 🔥 **{pod_key}**: KV cache nearly full ({kv_cache*100:.1f}%). May cause OOM.")
            if running == 0 and waiting == 0 and (prompt_tokens > 0 or gen_tokens > 0):
                alerts.append(f"- ℹ️ **{pod_key}**: Idle but has processed {int(success_total)} requests. Total tokens: {int(prompt_tokens + gen_tokens)}")
        
        output.append("")
        
        # Show failed pods if any
        if failed_pods:
            output.append("#### ⚠️ Failed to Query")
            for err in failed_pods:
                output.append(f"- {err}")
            output.append("")
        
        # Alerts and Recommendations
        if alerts:
            output.append("#### ⚠️ Alerts")
            output.extend(alerts)
            output.append("")
            output.append("#### 💡 Recommendations")
            output.append("- **High Queue**: Scale horizontally (add more vLLM pods) or vertically (increase GPU count)")
            output.append("- **High KV Cache Usage**: Reduce `max_model_len` or `gpu_memory_utilization` in vLLM config")
            output.append("- **Detailed Metrics**: Use `oc exec -n <ns> <pod> -- curl http://localhost:8000/metrics` for full data")
        else:
            output.append("#### ✅ All vLLM instances operating normally")
        
        return "\n".join(output)
    
    except OCError as e:
        return f"Error querying vLLM pods: {e}"
