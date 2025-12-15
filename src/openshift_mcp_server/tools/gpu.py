from openshift_mcp_server.utils.prometheus import query_prometheus, OCError
from openshift_mcp_server.utils.oc import run_oc_command
import logging

logger = logging.getLogger("openshift-mcp-server")

async def inspect_gpu_pod(namespace: str, pod_name: str) -> str:
    """
    Run 'nvidia-smi' inside a GPU-enabled pod to view real-time process and memory details.
    
    Why:
    - Debug OOM: See exact memory usage per process.
    - Verify allocation: Confirm the pod actually sees the GPU.
    - Check processes: Identify zombie processes or unexpected workloads.
    
    Args:
        namespace: Pod namespace
        pod_name: Pod name
        
    Returns:
        Output of nvidia-smi from inside the pod.
    """
    try:
        # First check if the pod is running
        status_cmd = ["get", "pod", pod_name, "-n", namespace, "-o", "jsonpath={.status.phase}"]
        phase = await run_oc_command(status_cmd)
        if phase.strip() != "Running":
            return f"❌ Pod {pod_name} is not in Running phase (current: {phase}). Cannot exec."

        # Run nvidia-smi
        cmd = ["exec", "-n", namespace, pod_name, "--", "nvidia-smi"]
        output = await run_oc_command(cmd)
        
        return f"### GPU Status for `{namespace}/{pod_name}`\n\n```\n{output}\n```"
        
    except OCError as e:
        if "executable file not found" in str(e):
             return f"❌ `nvidia-smi` not found in pod {pod_name}. The container might not have NVIDIA drivers or tools installed."
        return f"❌ Error running nvidia-smi: {e}"

async def check_gpu_health() -> str:
    """
    Check for GPU hardware errors (XID) and throttling events across the cluster.
    
    Why:
    - Detect Hardware Failures: XID errors often indicate physical GPU faults.
    - Explain Performance Issues: Thermal or Power throttling explains why a model is slow. 
    
    Returns:
        Markdown report of GPU health issues.
    """
    
    queries = {
        "xid_errors": "DCGM_FI_DEV_XID_ERRORS",
        "temp": "DCGM_FI_DEV_GPU_TEMP",
        "power": "DCGM_FI_DEV_POWER_USAGE",
        "throttle": "DCGM_FI_DEV_CLOCK_THROTTLE_REASONS"
    }
    
    try:
        results = {}
        for name, query in queries.items():
            try:
                # Get the last valid value in the last 5 minutes to ensure we don't miss transient drops
                # But simple query is usually enough for gauges
                res = await query_prometheus(query)
                if res.get("status") == "success":
                    results[name] = res.get("data", {}).get("result", [])
            except OCError:
                results[name] = []
                
        output = ["### GPU Health & Diagnostics"]
        
        # 1. Check for XID Errors (Critical)
        xid_errors = []
        for r in results.get("xid_errors", []):
            val = float(r.get("value", [0, "0"])[1])
            if val > 0:
                metric = r.get("metric", {})
                node = metric.get("node", metric.get("instance", "unknown"))
                gpu = metric.get("gpu", metric.get("GPU", "?"))
                xid_errors.append(f"- 🚨 **Node {node} GPU {gpu}**: XID Error Code {int(val)}")
        
        if xid_errors:
            output.append("#### ❌ Hardware Errors Detected")
            output.extend(xid_errors)
            output.append("  - **Action**: Contact infrastructure team. This usually indicates hardware failure.")
        else:
            output.append("#### ✅ No Hardware (XID) Errors")

        # 2. Check Throttling
        throttled = []
        for r in results.get("throttle", []):
            val = int(float(r.get("value", [0, "0"])[1]))
            if val > 0:
                metric = r.get("metric", {})
                node = metric.get("node", metric.get("instance", "unknown"))
                gpu = metric.get("gpu", metric.get("GPU", "?"))
                
                reasons = []
                if val & 1: reasons.append("GPU Idle") # Not really a throttle in bad sense
                if val & 2: reasons.append("Power Cap (Normal)")
                if val & 4: reasons.append("🔥 Thermal Slowdown")
                if val & 8: reasons.append("Power Supply Failure")
                if val & 16: reasons.append("Unknown")
                
                # Filter out "GPU Idle" or normal Power Cap unless strictly needed
                # For this report, we care about Thermal or HW issues
                critical_reasons = [r for r in reasons if "Thermal" in r or "Failure" in r]
                
                if critical_reasons:
                    throttled.append(f"- ⚠️ **Node {node} GPU {gpu}**: {', '.join(critical_reasons)}")
        
        if throttled:
            output.append("\n#### 🔥 Thermal/Power Throttling Events")
            output.extend(throttled)
        else:
            output.append("\n#### ✅ No Critical Throttling")

        # 3. High Temperature Check (> 80C)
        hot_gpus = []
        for r in results.get("temp", []):
            val = float(r.get("value", [0, "0"])[1])
            if val > 80:
                metric = r.get("metric", {})
                node = metric.get("node", metric.get("instance", "unknown"))
                gpu = metric.get("gpu", metric.get("GPU", "?"))
                hot_gpus.append(f"- **Node {node} GPU {gpu}**: {val:.1f}°C")
                
        if hot_gpus:
            output.append("\n#### 🌡️ High Temperatures (>80°C)")
            output.extend(hot_gpus)
            
        return "\n".join(output)

    except OCError as e:
        return f"Error checking GPU health: {e}"