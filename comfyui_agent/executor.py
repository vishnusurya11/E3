"""
Executor module for ComfyUI Agent.

Handles job execution, ComfyUI API communication, and the main execution loop.
Based on patterns from legacy comfyworkflowtrigger.py.
"""

import json
import os
import uuid
import time
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
import httpx
import websocket

from comfyui_agent.db_manager import (
    lease_next_job,
    complete_job,
    recover_orphans,
    get_job_by_config_name
)
from comfyui_agent.utils.file_utils import safe_move
import shutil
from comfyui_agent.utils.logger import get_logger

logger = get_logger(__name__)


class ComfyUIClient:
    """Client for ComfyUI API communication."""
    
    def __init__(self, base_url: str):
        """Initialize ComfyUI client.
        
        Args:
            base_url: Base URL for ComfyUI API (e.g., http://127.0.0.1:8188).
        """
        self.base_url = base_url.rstrip('/')
        self.client_id = str(uuid.uuid4())
    
    def queue_prompt(self, prompt: Dict[str, Any]) -> str:
        """Queue a prompt for execution.
        
        Args:
            prompt: Workflow prompt dictionary.
            
        Returns:
            Prompt ID for tracking.
            
        Raises:
            RuntimeError: If API call fails.
        """
        payload = {"prompt": prompt, "client_id": self.client_id}
        
        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{self.base_url}/prompt",
                    json=payload,
                    timeout=30.0
                )
                response.raise_for_status()
                result = response.json()
                
                if "prompt_id" not in result:
                    raise RuntimeError("No prompt_id in response")
                
                return result["prompt_id"]
        except Exception as e:
            raise RuntimeError(f"Failed to queue prompt: {e}")
    
    def wait_for_completion(self, prompt_id: str, timeout: int = 300) -> Dict[str, Any]:
        """Wait for prompt completion via WebSocket.
        
        Args:
            prompt_id: Prompt ID to wait for.
            timeout: Maximum time to wait in seconds.
            
        Returns:
            Result dictionary with outputs.
            
        Raises:
            RuntimeError: If execution fails or times out.
        """
        ws_url = f"ws://{self.base_url.replace('http://', '').replace('https://', '')}/ws?clientId={self.client_id}"
        
        ws = websocket.WebSocket()
        ws.connect(ws_url)
        
        start_time = time.time()
        outputs = []
        
        try:
            while True:
                if time.time() - start_time > timeout:
                    raise RuntimeError(f"Execution timeout after {timeout}s")
                
                message = ws.recv()
                
                if isinstance(message, str):
                    data = json.loads(message)
                    
                    if data.get("type") == "executing":
                        exec_data = data.get("data", {})
                        if exec_data.get("prompt_id") == prompt_id:
                            if exec_data.get("node") is None:
                                # Execution completed
                                break
                elif isinstance(message, bytes):
                    # Binary data (e.g., images)
                    outputs.append(message)
            
            return {
                "status": "completed",
                "outputs": outputs,
                "prompt_id": prompt_id
            }
        finally:
            ws.close()


def build_payload(workflow_id: str, inputs: Dict[str, Any],
                 workflows: Dict[str, Any]) -> Dict[str, Any]:
    """Build ComfyUI API payload from inputs.
    
    Maps inputs to the workflow template and validates required fields.
    
    Args:
        workflow_id: Workflow identifier.
        inputs: Input parameters for the workflow.
        workflows: Available workflow definitions.
        
    Returns:
        API payload dictionary.
        
    Raises:
        ValueError: If workflow unknown or inputs missing.
        
    Examples:
        >>> payload = build_payload("wf_test", {"prompt": "test"}, workflows)
    """
    if workflow_id not in workflows:
        raise ValueError(f"Unknown workflow: {workflow_id}")
    
    workflow_def = workflows[workflow_id]
    required_inputs = workflow_def.get("required_inputs", [])
    
    # Skip validation here - it's already done in validation.py
    # We trust the inputs are in node-specific format (e.g., "45_text", "31_seed")
    
    # Load workflow template JSON
    template_path = workflow_def.get("template_path")
    if not template_path:
        raise ValueError(f"No template_path for workflow: {workflow_id}")
    
    # Convert relative path to absolute
    if not os.path.isabs(template_path):
        base_dir = Path(__file__).parent.parent
        template_path = base_dir / template_path
    
    # Load template with UTF-8 encoding
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            workflow_template = json.load(f)
    except FileNotFoundError:
        raise ValueError(f"Template not found: {template_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in template: {e}")
    
    # Map node-specific inputs to workflow nodes
    # Format: "nodeID_parameter" (e.g., "45_text", "31_seed")
    for key, value in inputs.items():
        # Skip special keys
        if key == "outputs" or key.startswith("job_"):
            continue
            
        # Check if this is a node-specific input
        if "_" in key:
            parts = key.split("_", 1)
            if len(parts) == 2:
                node_id, param = parts
                
                # Check if this node exists in the workflow
                if node_id in workflow_template and "inputs" in workflow_template[node_id]:
                    node_inputs = workflow_template[node_id]["inputs"]
                    
                    # Update the parameter if it exists in this node
                    if param in node_inputs:
                        node_inputs[param] = value
                        logger.debug(f"Mapped {key} -> Node {node_id}.{param} = {value}")
                    else:
                        logger.warning(f"Parameter '{param}' not found in node {node_id}")
    
    # Handle output paths for SaveImage nodes
    for node_id, node in workflow_template.items():
        if "inputs" not in node:
            continue
            
            # Handle output paths if specified
            if node.get("class_type") == "SaveImage" and "outputs" in inputs:
                if "file_path" in inputs.get("outputs", {}):
                    output_path = Path(inputs["outputs"]["file_path"])
                    node_inputs["filename_prefix"] = output_path.stem
    
    return workflow_template


def invoke_comfyui(api_base_url: str, payload: Dict[str, Any],
                  timeout: int) -> Dict[str, Any]:
    """Invoke ComfyUI API with payload.
    
    Posts to ComfyUI and waits for completion via WebSocket.
    
    Args:
        api_base_url: ComfyUI API base URL.
        payload: Request payload.
        timeout: Timeout in seconds.
        
    Returns:
        Result dictionary with status and outputs.
        
    Raises:
        RuntimeError: On API errors or timeout.
        
    Examples:
        >>> result = invoke_comfyui("http://127.0.0.1:8000", payload, 300)
    """
    try:
        client = ComfyUIClient(api_base_url)
        
        # Queue the prompt
        prompt_id = client.queue_prompt(payload)
        logger.info(f"Queued prompt {prompt_id}")
        
        # Wait for completion
        result = client.wait_for_completion(prompt_id, timeout)
        
        return {
            "prompt_id": prompt_id,
            "status": "completed",
            "outputs": result.get("outputs", {})
        }
    except Exception as e:
        raise RuntimeError(f"ComfyUI invocation failed: {e}")


def write_outputs(result: Dict[str, Any], dest_paths: Dict[str, str]) -> Dict[str, Any]:
    """Write outputs from ComfyUI result to disk.
    
    Persists generated artifacts and returns metadata.
    
    Args:
        result: ComfyUI result dictionary.
        dest_paths: Destination paths configuration.
        
    Returns:
        Metadata dictionary with saved files info.
        
    Examples:
        >>> metadata = write_outputs(result, {"output_dir": "/outputs"})
    """
    output_dir = dest_paths.get("output_dir", "outputs")
    os.makedirs(output_dir, exist_ok=True)
    
    saved_files = []
    total_bytes = 0
    
    for i, output in enumerate(result.get("outputs", [])):
        if isinstance(output, dict):
            filename = output.get("filename", f"output_{i}.dat")
            data = output.get("data", b"")
        else:
            filename = f"output_{i}.dat"
            data = output if isinstance(output, bytes) else b""
        
        output_path = os.path.join(output_dir, filename)
        
        # Write file
        with open(output_path, "wb") as f:
            f.write(data)
        
        saved_files.append(output_path)
        total_bytes += len(data)
    
    return {
        "saved": saved_files,
        "bytes": total_bytes,
        "count": len(saved_files)
    }


def execute_job(job: Dict[str, Any], cfg: Dict[str, Any],
               workflows: Dict[str, Any], db_path: str) -> None:
    """Execute a single job end-to-end.
    
    Builds payload, invokes ComfyUI, writes outputs, updates DB,
    and moves YAML to finished folder.
    
    Args:
        job: Job dictionary from database.
        cfg: Global configuration.
        workflows: Available workflows.
        db_path: Database path.
        
    Examples:
        >>> execute_job(job, config, workflows, "db.sqlite")
    """
    job_id = job["id"]
    config_name = job["config_name"]
    
    logger.info(f"[EXECUTE] Starting job execution for ID {job_id}: {config_name}")
    
    try:
        # Load YAML config
        yaml_path = os.path.join(cfg["paths"]["jobs_processing"], config_name)
        logger.info(f"[EXECUTE] Looking for YAML at: {yaml_path}")
        
        # Try to find the file in subdirectories if not at root
        if not os.path.exists(yaml_path):
            logger.info(f"[EXECUTE] Not found at root, checking subdirectories...")
            # Extract job type from config name
            job_type = config_name.split("_")[0].lower()
            type_map = {"t2i": "image", "t2v": "video", "audio": "audio",
                       "speech": "speech", "3d": "3d"}
            subdir = type_map.get(job_type.lower(), job_type.lower())
            yaml_path = os.path.join(cfg["paths"]["jobs_processing"], subdir, config_name)
            logger.info(f"[EXECUTE] Checking: {yaml_path}")
        
        if not os.path.exists(yaml_path):
            # Try uppercase type folder
            yaml_path = os.path.join(cfg["paths"]["jobs_processing"],
                                    config_name.split("_")[0], config_name)
            logger.info(f"[EXECUTE] Checking uppercase folder: {yaml_path}")
        
        if not os.path.exists(yaml_path):
            # Check if file exists in finished folder (might be a retry of completed job)
            finished_path = os.path.join(cfg["paths"]["jobs_finished"],
                                        config_name.split("_")[0].lower(), config_name)
            if os.path.exists(finished_path):
                logger.warning(f"[EXECUTE] YAML found in finished folder, likely a retry: {finished_path}")
                yaml_path = finished_path
            else:
                logger.error(f"[EXECUTE] YAML not found in processing or finished: {config_name}")
                raise FileNotFoundError(f"YAML file not found in any expected location: {config_name}")
        
        logger.info(f"[EXECUTE] Found YAML at: {yaml_path}")
        with open(yaml_path, 'r', encoding='utf-8') as f:
            job_config = yaml.safe_load(f)
        logger.info(f"[EXECUTE] Loaded job config: {list(job_config.keys())}")
        
        # Build payload
        inputs = job_config.get("inputs", {})
        # Add outputs to inputs so build_payload can map them
        inputs["outputs"] = job_config.get("outputs", {})
        logger.info(f"[EXECUTE] Building payload for workflow: {job['workflow_id']}")
        logger.info(f"[EXECUTE] Inputs: {inputs}")
        payload = build_payload(job["workflow_id"], inputs, workflows)
        logger.info(f"[EXECUTE] Payload built successfully")
        
        # Invoke ComfyUI
        api_url = cfg["comfyui"]["api_base_url"]
        timeout = cfg["comfyui"]["timeout_seconds"]
        logger.info(f"[EXECUTE] Connecting to ComfyUI at: {api_url}")
        logger.info(f"[EXECUTE] Timeout set to: {timeout} seconds")
        result = invoke_comfyui(api_url, payload, timeout)
        logger.info(f"[EXECUTE] ComfyUI execution completed")
        
        # Write outputs
        output_config = job_config.get("outputs", {})
        dest_paths = {"output_dir": os.path.dirname(output_config.get("file_path", "outputs"))}
        metadata = write_outputs(result, dest_paths)
        
        # Success - update DB
        complete_job(db_path, job_id, success=True, updates={
            "metadata": json.dumps(metadata)
        })
        
        # Move YAML to finished, preserving subfolder structure
        # Only move if the file still exists (might have been moved by previous attempt)
        if os.path.exists(yaml_path):
            # Get relative path from processing folder
            processing_base = cfg["paths"]["jobs_processing"]
            relative_path = os.path.relpath(yaml_path, processing_base)
            
            # Build finished path with same subfolder structure
            finished_path = os.path.join(cfg["paths"]["jobs_finished"], relative_path)
            finished_dir = os.path.dirname(finished_path)
            os.makedirs(finished_dir, exist_ok=True)
            
            # Move file after successful completion
            shutil.move(yaml_path, finished_path)
            logger.info(f"[EXECUTE] Moved YAML to finished: {finished_path}")
        else:
            logger.info(f"[EXECUTE] YAML already moved or doesn't exist: {yaml_path}")
        
        logger.info(f"[EXECUTE] ✅ Job {config_name} completed successfully!")
        
    except Exception as e:
        # Failure - update DB with error
        logger.error(f"[EXECUTE] ❌ Job {config_name} failed: {e}")
        logger.error(f"[EXECUTE] Error type: {type(e).__name__}")
        import traceback
        logger.error(f"[EXECUTE] Traceback:\n{traceback.format_exc()}")
        complete_job(db_path, job_id, success=False, updates={
            "error_trace": str(e)
        })


def run_once(cfg: Dict[str, Any], workflows: Dict[str, Any],
            db_path: str, worker_id: str) -> bool:
    """Run one iteration of the executor loop.
    
    Recovers orphans, leases next job, and executes it.
    
    Args:
        cfg: Global configuration.
        workflows: Available workflows.
        db_path: Database path.
        worker_id: Worker identifier.
        
    Returns:
        True if work was done, False if idle.
        
    Examples:
        >>> did_work = run_once(config, workflows, "db.sqlite", "worker1")
    """
    logger.debug(f"[EXECUTOR] Checking for jobs...")
    
    # Recover orphaned jobs
    recovered = recover_orphans(db_path, datetime.now())
    if recovered > 0:
        logger.info(f"[EXECUTOR] Recovered {recovered} orphaned jobs")
    
    # Check what jobs exist in DB (only in debug mode)
    import sqlite3
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Only show detailed job list in debug mode
    if logger.isEnabledFor(10):  # DEBUG level
        cursor.execute("SELECT id, config_name, status, retries_attempted, retry_limit FROM comfyui_jobs")
        all_jobs = cursor.fetchall()
        
        if all_jobs:
            logger.debug(f"[EXECUTOR] Jobs in database:")
            for job in all_jobs:
                logger.debug(f"  - ID {job[0]}: {job[1]} | Status: {job[2]} | Retries: {job[3]}/{job[4]}")
        else:
            logger.debug(f"[EXECUTOR] No jobs in database")
    
    cursor.execute("SELECT COUNT(*) FROM comfyui_jobs WHERE status='pending'")
    pending_count = cursor.fetchone()[0]
    
    # Only log if there are pending jobs
    if pending_count > 0:
        logger.info(f"[EXECUTOR] Found {pending_count} pending job(s)")
    else:
        logger.debug(f"[EXECUTOR] No pending jobs")
    
    conn.close()
    
    # Lease next job
    if pending_count > 0:
        logger.info(f"[EXECUTOR] Attempting to lease next job for worker {worker_id}")
    
    job = lease_next_job(db_path, worker_id, lease_seconds=300)
    
    if not job:
        logger.debug(f"[EXECUTOR] No jobs available to process")
        return False  # No work available
    
    logger.info(f"[EXECUTOR] Successfully leased job ID {job['id']}: {job['config_name']}")
    logger.info(f"[EXECUTOR] Job details: workflow_id={job.get('workflow_id')}, priority={job.get('priority')}")
    
    # Execute the job
    logger.info(f"[EXECUTOR] Starting execution of job {job['config_name']}")
    execute_job(job, cfg, workflows, db_path)
    
    return True


def run_loop(cfg: Dict[str, Any], workflows: Dict[str, Any],
            db_path: str, worker_id: str, stop_event=None) -> None:
    """Run continuous executor loop.
    
    Keeps running until stop_event is set.
    
    Args:
        cfg: Global configuration.
        workflows: Available workflows.
        db_path: Database path.
        worker_id: Worker identifier.
        stop_event: Optional threading event to stop loop.
        
    Examples:
        >>> run_loop(config, workflows, "db.sqlite", "worker1")
    """
    poll_interval = cfg.get("poll_interval_ms", 1000) / 1000.0
    
    logger.info(f"[EXECUTOR LOOP] Starting executor loop for worker {worker_id}")
    logger.info(f"[EXECUTOR LOOP] Poll interval: {poll_interval}s")
    logger.info(f"[EXECUTOR LOOP] Database: {db_path}")
    logger.info(f"[EXECUTOR LOOP] ComfyUI URL: {cfg.get('comfyui', {}).get('api_base_url')}")
    
    iteration = 0
    while stop_event is None or not stop_event.is_set():
        try:
            iteration += 1
            logger.debug(f"[EXECUTOR LOOP] Iteration {iteration} - calling run_once...")
            did_work = run_once(cfg, workflows, db_path, worker_id)
            
            if not did_work:
                # No work available, sleep before checking again
                logger.debug(f"[EXECUTOR LOOP] No work found, sleeping for {poll_interval}s")
                if stop_event:
                    stop_event.wait(poll_interval)
                else:
                    time.sleep(poll_interval)
            else:
                logger.info(f"[EXECUTOR LOOP] Work completed in iteration {iteration}")
        except KeyboardInterrupt:
            logger.info("Executor loop interrupted by user")
            break
        except Exception as e:
            logger.error(f"Error in executor loop: {e}")
            time.sleep(poll_interval)
    
    logger.info(f"Executor loop stopped for worker {worker_id}")