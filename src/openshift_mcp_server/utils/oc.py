import asyncio
import json
import logging
import shlex
import subprocess

logger = logging.getLogger("openshift-mcp-server")

class OCError(Exception):
    """Raised when an oc command fails."""
    pass

async def run_oc_command(args: list[str]) -> str:
    """
    Execute an oc command and return stdout as string.
    
    Args:
        args: List of arguments to pass to oc (e.g., ["get", "pods"])
        
    Returns:
        Standard output string
        
    Raises:
        OCError: If the command returns a non-zero exit code
    """
    cmd = ["oc"] + args
    cmd_str = shlex.join(cmd)
    logger.debug(f"Executing: {cmd_str}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        stdout_str = stdout.decode("utf-8")
        stderr_str = stderr.decode("utf-8")

        if proc.returncode != 0:
            logger.error(f"Command failed: {cmd_str}\nStderr: {stderr_str}")
            raise OCError(f"Command failed with exit code {proc.returncode}: {stderr_str}")

        return stdout_str

    except FileNotFoundError:
        raise OCError("The 'oc' CLI tool is not found in PATH.")
    except Exception as e:
        raise OCError(f"Unexpected error executing oc: {e}")

async def run_oc_json(args: list[str]) -> dict | list:
    """
    Execute an oc command and parse the output as JSON.
    Automatically adds '-o json' if not present (unless it's a raw command).
    
    Args:
        args: List of arguments
        
    Returns:
        Parsed JSON object (dict or list)
    """
    # Auto-append -o json for get/list commands if not present
    if "get" in args and "-o" not in args and "--output" not in args:
        args = args + ["-o", "json"]

    stdout = await run_oc_command(args)
    
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise OCError(f"Failed to parse JSON output from oc: {e}")

async def get_node_stats_summary(node_name: str) -> dict:
    """
    Fetch node stats summary using the raw API endpoint.
    Equivalent to: oc get --raw /api/v1/nodes/{node}/proxy/stats/summary
    """
    try:
        stdout = await run_oc_command([
            "get", "--raw", 
            f"/api/v1/nodes/{node_name}/proxy/stats/summary"
        ])
        return json.loads(stdout)
    except json.JSONDecodeError:
        raise OCError(f"Failed to parse stats summary for node {node_name}")
