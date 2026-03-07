"""
ComfyUI Workflow Trigger Module

Provides a simple function to trigger ComfyUI workflows, wait for completion,
and return results. Designed for easy import and use in Phase 5 workflows.

Usage:
    from src.comfyui_trigger import trigger_comfy

    result = trigger_comfy(
        workflow_json_path="path/to/workflow.json",
        replacements={
            "45_text": "A beautiful portrait",
            "31_seed": 12345,
            "3_steps": 30
        }
    )

    print(f"Status: {result['status']}")
    print(f"Prompt ID: {result['prompt_id']}")
"""

import json
import uuid
import time
import httpx
import websocket
from typing import Dict, Any, List
from pathlib import Path


class ComfyUIClient:
    """Internal client for ComfyUI API communication."""

    def __init__(self, base_url: str):
        """
        Initialize ComfyUI client.

        Args:
            base_url: Base URL of ComfyUI API (e.g., "http://127.0.0.1:8188")
        """
        self.base_url = base_url.rstrip('/')
        self.client_id = str(uuid.uuid4())

    def queue_prompt(self, prompt: Dict[str, Any]) -> str:
        """
        Queue a prompt for execution.

        Args:
            prompt: The workflow dictionary to execute

        Returns:
            prompt_id: Unique identifier for tracking this execution

        Raises:
            ConnectionError: Cannot reach ComfyUI API
            RuntimeError: Invalid response from API
        """
        payload = {
            "prompt": prompt,
            "client_id": self.client_id
        }

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
                    raise RuntimeError(
                        f"No prompt_id in ComfyUI response: {result}"
                    )

                return result["prompt_id"]

        except httpx.ConnectError as e:
            raise ConnectionError(
                f"Cannot connect to ComfyUI at {self.base_url}. "
                f"Is ComfyUI running? Error: {e}"
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(
                f"ComfyUI API error: {e.response.status_code} - {e.response.text}"
            )

    def wait_for_completion(
        self,
        prompt_id: str,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Wait for prompt completion via WebSocket.

        Args:
            prompt_id: The prompt ID to wait for
            timeout: Maximum seconds to wait

        Returns:
            Dict with status and outputs

        Raises:
            TimeoutError: Execution exceeds timeout
            ConnectionError: WebSocket connection failed
        """
        # Convert HTTP URL to WebSocket URL
        ws_base = self.base_url.replace('http://', '').replace('https://', '')
        ws_url = f"ws://{ws_base}/ws?clientId={self.client_id}"

        ws = None
        start_time = time.time()
        outputs: List[bytes] = []

        try:
            ws = websocket.WebSocket()
            ws.connect(ws_url)

            while True:
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise TimeoutError(
                        f"Workflow execution timeout after {timeout}s. "
                        f"Prompt ID: {prompt_id}"
                    )

                # Receive message with timeout
                ws.settimeout(1.0)
                try:
                    message = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue

                # Handle JSON messages
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        continue

                    # Check for execution completion
                    if data.get("type") == "executing":
                        exec_data = data.get("data", {})
                        if exec_data.get("prompt_id") == prompt_id:
                            # When node is None, execution is complete
                            if exec_data.get("node") is None:
                                return {
                                    "status": "completed",
                                    "outputs": outputs,
                                    "prompt_id": prompt_id
                                }

                # Handle binary data (images, etc.)
                elif isinstance(message, bytes):
                    outputs.append(message)

        except websocket.WebSocketException as e:
            raise ConnectionError(
                f"WebSocket connection error: {e}"
            )
        finally:
            if ws:
                try:
                    ws.close()
                except:
                    pass


def trigger_comfy(
    workflow_json_path: str,
    replacements: Dict[str, Any],
    comfyui_url: str = "http://127.0.0.1:8188",
    timeout: int = 300
) -> Dict[str, Any]:
    """
    Trigger a ComfyUI workflow and wait for completion.

    This function:
    1. Loads the workflow JSON from the specified path
    2. Applies value replacements to workflow nodes
    3. Submits the workflow to ComfyUI via HTTP API
    4. Waits for completion via WebSocket
    5. Returns results with execution metadata

    Args:
        workflow_json_path: Path to the ComfyUI workflow JSON file
        replacements: Dict mapping "nodeID_parameter" to values.
                     Format: {"45_text": "A portrait", "31_seed": 12345}
                     Keys are split on underscore: nodeID_parameter
                     Updates workflow[nodeID]["inputs"][parameter] = value
        comfyui_url: Base URL of ComfyUI API (default: http://127.0.0.1:8188)
        timeout: Max seconds to wait for completion (default: 300)

    Returns:
        Dict with keys:
            - prompt_id (str): ComfyUI prompt identifier
            - status (str): "completed", "timeout", or "error"
            - outputs (List[bytes]): Binary outputs collected (images, etc.)
            - execution_time (float): Duration in seconds
            - error (str, optional): Error message if status is "error"

    Raises:
        FileNotFoundError: Workflow JSON file not found
        KeyError: Invalid node ID or parameter in replacements
        ConnectionError: Cannot reach ComfyUI API
        TimeoutError: Execution exceeds timeout

    Example:
        >>> result = trigger_comfy(
        ...     workflow_json_path="workflows/portrait.json",
        ...     replacements={
        ...         "45_text": "A beautiful portrait",
        ...         "31_seed": 12345,
        ...         "3_steps": 30
        ...     }
        ... )
        >>> print(f"Status: {result['status']}")
        >>> print(f"Execution time: {result['execution_time']}s")
    """
    start_time = time.time()

    try:
        # 1. Load workflow JSON
        workflow_path = Path(workflow_json_path)
        if not workflow_path.exists():
            raise FileNotFoundError(
                f"Workflow JSON not found: {workflow_json_path}"
            )

        with open(workflow_path, 'r', encoding='utf-8') as f:
            workflow = json.load(f)

        # 2. Apply replacements to workflow nodes
        for key, value in replacements.items():
            # Split on first underscore: "45_text" -> node_id="45", param="text"
            if "_" not in key:
                raise KeyError(
                    f"Invalid replacement key '{key}'. "
                    f"Expected format: 'nodeID_parameter' (e.g., '45_text')"
                )

            parts = key.split("_", 1)
            if len(parts) != 2:
                raise KeyError(
                    f"Invalid replacement key '{key}'. "
                    f"Expected format: 'nodeID_parameter'"
                )

            node_id, param = parts

            # Validate node exists
            if node_id not in workflow:
                raise KeyError(
                    f"Node '{node_id}' not found in workflow. "
                    f"Available nodes: {list(workflow.keys())}"
                )

            # Validate node has inputs
            if "inputs" not in workflow[node_id]:
                raise KeyError(
                    f"Node '{node_id}' has no inputs section"
                )

            # Apply the replacement
            node_inputs = workflow[node_id]["inputs"]
            if param not in node_inputs:
                raise KeyError(
                    f"Parameter '{param}' not found in node '{node_id}'. "
                    f"Available parameters: {list(node_inputs.keys())}"
                )

            node_inputs[param] = value

        # 3. Submit to ComfyUI and wait for completion
        client = ComfyUIClient(comfyui_url)
        prompt_id = client.queue_prompt(workflow)
        result = client.wait_for_completion(prompt_id, timeout)

        # 4. Calculate execution time
        execution_time = time.time() - start_time

        # 5. Return results
        return {
            "prompt_id": prompt_id,
            "status": result["status"],
            "outputs": result["outputs"],
            "execution_time": execution_time
        }

    except (FileNotFoundError, KeyError, ConnectionError, TimeoutError) as e:
        # Re-raise expected errors
        raise

    except Exception as e:
        # Catch unexpected errors
        execution_time = time.time() - start_time
        return {
            "prompt_id": None,
            "status": "error",
            "outputs": [],
            "execution_time": execution_time,
            "error": str(e)
        }


def upload_image_to_comfyui(
    image_path: Path,
    comfyui_url: str = "http://127.0.0.1:8188",
) -> str:
    """Upload an image to ComfyUI's input/ directory via the /upload/image API.

    ComfyUI's LoadImage node reads from the input/ directory. To chain workflow
    outputs as inputs to subsequent workflows, we upload the output image back
    to the input/ directory.

    Args:
        image_path: Absolute path to the image file on disk.
        comfyui_url: Base URL of ComfyUI API.

    Returns:
        The filename as stored in ComfyUI's input/ directory.
        Use this value in LoadImage node replacements.

    Raises:
        FileNotFoundError: Image file does not exist.
        ConnectionError: Cannot reach ComfyUI API.
        RuntimeError: Upload failed (non-200 response).
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    base_url = comfyui_url.rstrip("/")

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    try:
        with httpx.Client() as client:
            response = client.post(
                f"{base_url}/upload/image",
                files={"image": (image_path.name, image_bytes, "image/png")},
                data={"overwrite": "true"},
                timeout=30.0,
            )
            response.raise_for_status()
            result = response.json()

            if "name" not in result:
                raise RuntimeError(
                    f"No 'name' in ComfyUI upload response: {result}"
                )

            return result["name"]

    except httpx.ConnectError as e:
        raise ConnectionError(
            f"Cannot connect to ComfyUI at {base_url}. "
            f"Is ComfyUI running? Error: {e}"
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"ComfyUI upload error: {e.response.status_code} - {e.response.text}"
        )


if __name__ == "__main__":
    import sys

    # =============================================================================
    # CONFIGURATION - Edit these variables as needed
    # =============================================================================
    workflow_path = r"D:\Projects\KingdomOfViSuReNa\alpha\house_of_novels\workflows\z_image_turbo_example.json"  # Path to your ComfyUI workflow JSON file
    replacements_dict = {
        "11_text": "Immersive mid-action anime wide shot of an unknown detective, cloaked in a swirling icy blue cape, as they launch themselves towards a shimmering magical compass suspended in mid-air, surrounded by a whirlwind of sparkling frost and energy. Behind them, a towering figure of a corrupt official looms menacingly, dark shadows casting over their face, with wisps of smoke and ice particles swirling around in a chaotic dance. The camera captures the dynamic motion from a low angle, emphasizing the grand scale of the Frozen Heart Square, with its majestic ice sculptures and vibrant dye flowers contrasting against the stark white snow. Dramatic rim lighting highlights the detective's determined expression, while beams of soft volumetric light break through the haze, creating a mystical atmosphere. The color palette combines cool icy blues and whites with vibrant reds and golds from the magical effects, evoking a sense of urgent hope amidst impending danger. Title \"The Compass of Hope\" in bold metallic serif font at bottom third, with a glowing outline that reflects the magic of the compass. Emotional tone: spirited determination and the thrill of an epic battle for freedom. 8k, ultra-detailed, theatrical movie poster, explosive magical effects, professional blockbuster quality, action fantasy style.",
        "10_filename_prefix": "api/ComfyUI"
    }

    COMFYUI_URL = "http://127.0.0.1:8188"
    TIMEOUT = 300
    SAVE_OUTPUT_DIR = None  # Set to a path like "output/test" to save images

    # =============================================================================
    # Execute workflow
    # =============================================================================
    print(f"Triggering ComfyUI workflow: {workflow_path}")
    print(f"Replacements: {replacements_dict}")
    print(f"URL: {COMFYUI_URL}")
    print(f"Timeout: {TIMEOUT}s")
    print("-" * 60)

    try:
        result = trigger_comfy(
            workflow_json_path=workflow_path,
            replacements=replacements_dict,
            comfyui_url=COMFYUI_URL,
            timeout=TIMEOUT
        )

        print(f"\n✅ Status: {result['status']}")
        print(f"Prompt ID: {result['prompt_id']}")
        print(f"Execution time: {result['execution_time']:.2f}s")
        print(f"Outputs: {len(result['outputs'])} file(s)")

        # Save outputs if directory specified
        if SAVE_OUTPUT_DIR and result['outputs']:
            output_dir = Path(SAVE_OUTPUT_DIR)
            output_dir.mkdir(parents=True, exist_ok=True)

            for i, output_bytes in enumerate(result['outputs']):
                output_path = output_dir / f"output_{result['prompt_id']}_{i}.png"
                with open(output_path, "wb") as f:
                    f.write(output_bytes)
                print(f"Saved: {output_path}")

        if result['status'] != 'completed':
            print(f"\n⚠️  Error: {result.get('error', 'Unknown error')}")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
