from openshift_mcp_server.utils.oc import run_oc_json, run_oc_command, OCError
import logging

logger = logging.getLogger("openshift-mcp-server")

async def get_pod_logs(
    namespace: str,
    pod_name: str,
    container: str | None = None,
    previous: bool = False,
    tail: int = 100,
    since: str | None = None
) -> str:
    """
    Retrieve container logs from a pod.
    
    Args:
        namespace: Pod namespace
        pod_name: Pod name
        container: Specific container name (if None, gets all containers)
        previous: Get logs from previous container instance
        tail: Number of recent lines to retrieve (default: 100)
        since: Time duration to retrieve logs from (e.g., "1h", "30m")
        
    Returns:
        Formatted logs with container separation
    """
    try:
        # Get pod details to list containers
        pod_json = await run_oc_json(["get", "pod", pod_name, "-n", namespace])
        
        spec = pod_json.get("spec", {})
        status = pod_json.get("status", {})
        
        # Get all container names
        containers = []
        if container:
            # Verify the specified container exists
            all_containers = [c["name"] for c in spec.get("containers", [])]
            all_containers.extend([c["name"] for c in spec.get("initContainers", [])])
            if container not in all_containers:
                return f"❌ Container '{container}' not found in pod {namespace}/{pod_name}\n\nAvailable containers: {', '.join(all_containers)}"
            containers = [container]
        else:
            # Get all containers (init + regular)
            containers = [c["name"] for c in spec.get("initContainers", [])]
            containers.extend([c["name"] for c in spec.get("containers", [])])
        
        if not containers:
            return f"❌ No containers found in pod {namespace}/{pod_name}"
        
        output = [f"### Pod Logs: `{namespace}/{pod_name}`\n"]
        
        for container_name in containers:
            # Find container status
            container_statuses = status.get("containerStatuses", []) + status.get("initContainerStatuses", [])
            container_status = next((cs for cs in container_statuses if cs["name"] == container_name), None)
            
            # Determine if we should get previous logs
            get_previous = previous
            state_info = ""
            
            if container_status:
                state = container_status.get("state", {})
                restart_count = container_status.get("restartCount", 0)
                
                if "running" in state:
                    state_info = f"Running (Restarts: {restart_count})"
                elif "waiting" in state:
                    reason = state["waiting"].get("reason", "Unknown")
                    state_info = f"Waiting ({reason})"
                    # Auto-fetch previous logs for CrashLoopBackOff
                    if reason == "CrashLoopBackOff" and restart_count > 0:
                        get_previous = True
                        state_info += " - Showing previous logs"
                elif "terminated" in state:
                    reason = state["terminated"].get("reason", "Unknown")
                    exit_code = state["terminated"].get("exitCode", "N/A")
                    state_info = f"Terminated ({reason}, Exit: {exit_code})"
            
            log_type = "PREVIOUS" if get_previous else "CURRENT"
            output.append(f"#### Container: `{container_name}` [{log_type}]")
            if state_info:
                output.append(f"*State: {state_info}*\n")
            
            # Build log command
            log_cmd = ["logs", pod_name, "-n", namespace, "-c", container_name, f"--tail={tail}"]
            if get_previous:
                log_cmd.append("--previous")
            if since:
                log_cmd.append(f"--since={since}")
            
            try:
                logs = await run_oc_command(log_cmd)
                
                if not logs.strip():
                    output.append("*(No logs available)*\n")
                else:
                    # Limit output to prevent overwhelming responses
                    lines = logs.strip().split("\n")
                    if len(lines) > tail:
                        lines = lines[-tail:]
                        output.append(f"*(Showing last {tail} lines)*")
                    
                    output.append("```")
                    output.append("\n".join(lines))
                    output.append("```\n")
                    
            except OCError as e:
                error_msg = str(e)
                if "previous terminated container" in error_msg.lower() or "not found" in error_msg.lower():
                    output.append("*(No previous logs available - container has not restarted)*\n")
                else:
                    output.append(f"⚠️ Error retrieving logs: {error_msg}\n")
        
        return "\n".join(output)
        
    except OCError as e:
        return f"❌ Error accessing pod {namespace}/{pod_name}: {e}"

async def get_pod_diagnostics(namespace: str, pod_name: str) -> str:
    """
    Comprehensive pod health analysis with events, status, and actionable recommendations.
    
    Args:
        namespace: Pod namespace
        pod_name: Pod name
        
    Returns:
        Detailed diagnostic report with recommendations
    """
    try:
        # Get pod details
        pod_json = await run_oc_json(["get", "pod", pod_name, "-n", namespace])
        
        metadata = pod_json.get("metadata", {})
        spec = pod_json.get("spec", {})
        status = pod_json.get("status", {})
        
        output = [f"### Pod Diagnostics: `{namespace}/{pod_name}`\n"]
        
        # Pod Status
        output.append("#### Pod Status")
        phase = status.get("phase", "Unknown")
        node = spec.get("nodeName", "Not assigned")
        start_time = status.get("startTime", "N/A")
        qos_class = status.get("qosClass", "N/A")
        
        output.append(f"- **Phase**: {phase}")
        output.append(f"- **Node**: {node}")
        output.append(f"- **QoS Class**: {qos_class}")
        output.append(f"- **Start Time**: {start_time}\n")
        
        # Pod Conditions
        conditions = status.get("conditions", [])
        if conditions:
            output.append("**Conditions**:")
            for cond in conditions:
                cond_type = cond.get("type")
                cond_status = cond.get("status")
                reason = cond.get("reason", "")
                message = cond.get("message", "")
                
                icon = "✅" if cond_status == "True" else "❌"
                output.append(f"- {icon} {cond_type}: {cond_status}")
                if reason and cond_status != "True":
                    output.append(f"  - Reason: {reason}")
                if message and cond_status != "True":
                    output.append(f"  - {message}")
            output.append("")
        
        # Container Status
        output.append("#### Container Status")
        container_statuses = status.get("containerStatuses", [])
        init_container_statuses = status.get("initContainerStatuses", [])
        
        if container_statuses or init_container_statuses:
            output.append("| Container | Restarts | State | Reason | Exit Code | Ready |")
            output.append("|-----------|----------|-------|--------|-----------|-------|")
            
            all_statuses = init_container_statuses + container_statuses
            recommendations = []
            
            for cs in all_statuses:
                name = cs.get("name", "unknown")
                restarts = cs.get("restartCount", 0)
                ready = "✅" if cs.get("ready", False) else "❌"
                state = cs.get("state", {})
                
                state_str = "Unknown"
                reason = "-"
                exit_code = "-"
                
                if "running" in state:
                    state_str = "Running"
                    reason = "-"
                elif "waiting" in state:
                    state_str = "Waiting"
                    reason = state["waiting"].get("reason", "Unknown")
                    
                    # Add recommendations based on waiting reason
                    if reason == "ImagePullBackOff" or reason == "ErrImagePull":
                        recommendations.append(f"- **{name}**: Image pull failed. Check image name and registry access.")
                    elif reason == "CrashLoopBackOff":
                        recommendations.append(f"- **{name}**: Container is crash looping. Check logs with `get_pod_logs`.")
                    elif reason == "CreateContainerConfigError":
                        recommendations.append(f"- **{name}**: Configuration error. Check ConfigMaps/Secrets.")
                        
                elif "terminated" in state:
                    state_str = "Terminated"
                    reason = state["terminated"].get("reason", "Unknown")
                    exit_code = str(state["terminated"].get("exitCode", "N/A"))
                    
                    if reason == "OOMKilled":
                        recommendations.append(f"- **{name}**: OOMKilled (Exit {exit_code}). Increase memory limits.")
                    elif reason == "Error" and exit_code != "0":
                        recommendations.append(f"- **{name}**: Exited with error code {exit_code}. Check application logs.")
                
                # Flag high restart counts
                if restarts > 5:
                    recommendations.append(f"- **{name}**: High restart count ({restarts}). Pod is unstable.")
                
                output.append(f"| `{name}` | **{restarts}** | {state_str} | {reason} | {exit_code} | {ready} |")
            
            output.append("")
        
        # Get Events
        try:
            events_json = await run_oc_json([
                "get", "events", "-n", namespace,
                "--field-selector", f"involvedObject.name={pod_name}",
                "--sort-by", ".lastTimestamp"
            ])
            
            events = events_json.get("items", [])
            
            # Filter to Warning/Error events and limit to last 20
            warning_events = [e for e in events if e.get("type") in ["Warning", "Error"]]
            warning_events = warning_events[-20:]  # Last 20
            
            if warning_events:
                output.append("#### Recent Events (Warnings/Errors)")
                output.append("| Time | Type | Reason | Message |")
                output.append("|------|------|--------|---------|")
                
                for event in reversed(warning_events):  # Most recent first
                    event_type = event.get("type", "Unknown")
                    reason = event.get("reason", "Unknown")
                    message = event.get("message", "")
                    last_timestamp = event.get("lastTimestamp", "")
                    
                    # Truncate long messages
                    if len(message) > 80:
                        message = message[:77] + "..."
                    
                    output.append(f"| {last_timestamp} | {event_type} | {reason} | {message} |")
                
                output.append("")
                
        except OCError as e:
            logger.warning(f"Could not fetch events: {e}")
        
        # Recommendations
        if recommendations:
            output.append("#### 💡 Recommendations")
            for rec in recommendations:
                output.append(rec)
        else:
            output.append("#### ✅ No issues detected")
        
        return "\n".join(output)
        
    except OCError as e:
        return f"❌ Error accessing pod {namespace}/{pod_name}: {e}"
