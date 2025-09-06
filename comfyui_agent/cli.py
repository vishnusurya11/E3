#!/usr/bin/env python
"""
CLI interface for ComfyUI Agent.

Provides command-line tools for managing and monitoring the agent.
"""

import typer
import os
import sys
import threading
import uvicorn
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich import box
import time

from comfyui_agent.utils.config_loader import load_global_config, load_workflows
from comfyui_agent.utils.logger import setup_logging, get_logger
from comfyui_agent.db_manager import init_db, list_jobs_by_status
from comfyui_agent.monitor import run_monitor_loop
from comfyui_agent.executor import run_loop as run_executor_loop
from comfyui_agent.queue_manager import set_job_priority, apply_god_mode
from comfyui_agent.ui_server import app as fastapi_app, set_db_path

# Create Typer app
app = typer.Typer(
    name="e3",
    help="E3 ComfyUI Agent - AI Media Generation Pipeline",
    add_completion=False
)

console = Console()
logger = get_logger(__name__)

# Default paths
DEFAULT_CONFIG_PATH = "comfyui_agent/config/global_config.yaml"
DEFAULT_WORKFLOWS_PATH = "comfyui_agent/config/workflows.yaml"


def get_config_and_db(config_path: str = None) -> tuple:
    """Load configuration and initialize database.
    
    Returns:
        Tuple of (config, workflows, db_path).
    """
    try:
        config = load_global_config()  # Uses E3_ENV environment variable
        workflows = load_workflows(DEFAULT_WORKFLOWS_PATH) if os.path.exists(DEFAULT_WORKFLOWS_PATH) else {}
        db_path = config["paths"]["database"]
        
        # Ensure database is initialized
        init_db(db_path)
        
        return config, workflows, db_path
    except Exception as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        console.print(f"[yellow]Make sure E3_ENV is set (alpha/prod) and run 'python initialize.py' first[/yellow]")
        sys.exit(1)


@app.command()
def monitor(
    once: bool = typer.Option(False, "--once", help="Run once instead of loop"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output")
):
    """Start the monitor service to watch for new jobs."""
    if verbose:
        setup_logging(level="DEBUG")
    else:
        setup_logging(level="INFO")
    
    cfg, workflows, db_path = get_config_and_db(config)
    
    if once:
        console.print("[cyan]Running monitor scan once...[/cyan]")
        from comfyui_agent.monitor import scan_once
        results = scan_once(cfg, workflows, db_path)
        
        accepted = len([r for r in results if r["status"] == "accepted"])
        rejected = len([r for r in results if r["status"] == "rejected"])
        
        console.print(f"[green]Accepted: {accepted}[/green], [red]Rejected: {rejected}[/red]")
    else:
        console.print("[cyan]Starting monitor loop...[/cyan]")
        console.print(f"Watching: {cfg['paths']['jobs_processing']}")
        console.print("Press Ctrl+C to stop")
        
        try:
            run_monitor_loop(cfg, workflows, db_path)
        except KeyboardInterrupt:
            console.print("\n[yellow]Monitor stopped[/yellow]")


@app.command()
def run(
    once: bool = typer.Option(False, "--once", help="Run once instead of loop"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file path"),
    worker_id: str = typer.Option("worker1", "--worker", help="Worker ID"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output")
):
    """Start the executor service to process jobs."""
    if verbose:
        setup_logging(level="DEBUG")
    else:
        setup_logging(level="INFO")
    
    cfg, workflows, db_path = get_config_and_db(config)
    
    if once:
        console.print("[cyan]Running executor once...[/cyan]")
        from comfyui_agent.executor import run_once
        did_work = run_once(cfg, workflows, db_path, worker_id)
        
        if did_work:
            console.print("[green]Job executed successfully[/green]")
        else:
            console.print("[yellow]No jobs available[/yellow]")
    else:
        console.print("[cyan]Starting executor loop...[/cyan]")
        console.print(f"Worker ID: {worker_id}")
        console.print(f"ComfyUI: {cfg['comfyui']['api_base_url']}")
        console.print("Press Ctrl+C to stop")
        
        try:
            run_executor_loop(cfg, workflows, db_path, worker_id)
        except KeyboardInterrupt:
            console.print("\n[yellow]Executor stopped[/yellow]")


@app.command()
def start(
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file path"),
    ui_port: int = typer.Option(8080, "--ui-port", help="UI server port"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output")
):
    """Start all services (monitor, executor, and UI)."""
    if verbose:
        setup_logging(level="DEBUG")
    else:
        setup_logging(level="INFO")
    
    cfg, workflows, db_path = get_config_and_db(config)
    set_db_path(db_path)
    
    console.print("[cyan]Starting all services...[/cyan]")
    
    # Start monitor in thread
    monitor_stop = threading.Event()
    monitor_thread = threading.Thread(
        target=run_monitor_loop,
        args=(cfg, workflows, db_path, monitor_stop)
    )
    monitor_thread.daemon = True
    monitor_thread.start()
    console.print("[green]✓ Monitor started[/green]")
    
    # Start executor in thread
    executor_stop = threading.Event()
    executor_thread = threading.Thread(
        target=run_executor_loop,
        args=(cfg, workflows, db_path, "worker1", executor_stop)
    )
    executor_thread.daemon = True
    executor_thread.start()
    console.print("[green]✓ Executor started[/green]")
    
    # Start UI server
    console.print(f"[green]✓ Starting UI server on http://127.0.0.1:{ui_port}[/green]")
    console.print("[yellow]Press Ctrl+C to stop all services[/yellow]")
    
    try:
        uvicorn.run(fastapi_app, host="127.0.0.1", port=ui_port, log_level="error")
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping all services...[/yellow]")
        monitor_stop.set()
        executor_stop.set()
        console.print("[green]All services stopped[/green]")


@app.command("queue")
def queue_cmd():
    """Queue management commands."""
    pass


@app.command("queue ls")
def queue_ls(
    status: Optional[str] = typer.Option(None, "--status", "-s", 
                                         help="Filter by status (pending/processing/done/failed)"),
    config: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file path")
):
    """List jobs in the queue."""
    cfg, _, db_path = get_config_and_db(config)
    
    jobs = list_jobs_by_status(db_path, status)
    
    if not jobs:
        console.print("[yellow]No jobs found[/yellow]")
        return
    
    # Create table
    table = Table(title="Job Queue", box=box.ROUNDED)
    table.add_column("Config Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Priority", justify="right")
    table.add_column("Retries", justify="right")
    
    for job in jobs:
        status_style = {
            "pending": "yellow",
            "processing": "blue",
            "done": "green",
            "failed": "red"
        }.get(job["status"], "white")
        
        table.add_row(
            job["config_name"],
            job["job_type"],
            f"[{status_style}]{job['status']}[/{status_style}]",
            str(job["priority"]),
            str(job.get("retries_attempted", 0))
        )
    
    console.print(table)


@app.command("queue set-priority")
def queue_set_priority(
    config_name: str = typer.Argument(..., help="Config filename"),
    priority: int = typer.Argument(..., help="New priority (1-999)"),
    config_path: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file path")
):
    """Set priority for a job."""
    cfg, _, db_path = get_config_and_db(config_path)
    
    try:
        set_job_priority(db_path, config_name, priority)
        console.print(f"[green]Priority updated to {priority} for {config_name}[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@app.command("queue god-mode")
def queue_god_mode(
    config_name: str = typer.Argument(..., help="Config filename"),
    config_path: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file path")
):
    """Apply God Mode to a job (set priority to 1)."""
    cfg, _, db_path = get_config_and_db(config_path)
    
    try:
        apply_god_mode(db_path, config_name)
        console.print(f"[green]God Mode applied to {config_name} (priority = 1)[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@app.command("retry")
def retry(
    config_name: str = typer.Argument(..., help="Config filename to retry"),
    config_path: str = typer.Option(DEFAULT_CONFIG_PATH, "--config", help="Config file path")
):
    """Retry a failed job."""
    cfg, _, db_path = get_config_and_db(config_path)
    
    from comfyui_agent.db_manager import get_job_by_config_name, get_db_connection
    
    job = get_job_by_config_name(db_path, config_name)
    if not job:
        console.print(f"[red]Job {config_name} not found[/red]")
        return
    
    if job["status"] != "failed":
        console.print(f"[yellow]Job is not failed (status: {job['status']})[/yellow]")
        return
    
    # Reset to pending
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE comfyui_jobs
            SET status = 'pending',
                error_trace = NULL
            WHERE config_name = ?
        """, (config_name,))
    
    console.print(f"[green]Job {config_name} queued for retry[/green]")


@app.command("init")
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files")
):
    """Initialize the ComfyUI Agent environment."""
    console.print("[cyan]Initializing E3 ComfyUI Agent...[/cyan]")
    
    # Create directory structure
    dirs = [
        "comfyui_agent/config",
        "comfyui_jobs/processing/image",
        "comfyui_jobs/processing/video",
        "comfyui_jobs/processing/audio",
        "comfyui_jobs/processing/speech",
        "comfyui_jobs/processing/3d",
        "comfyui_jobs/finished/image",
        "comfyui_jobs/finished/video",
        "comfyui_jobs/finished/audio",
        "comfyui_jobs/finished/speech",
        "comfyui_jobs/finished/3d",
        "database",
        "workflows"
    ]
    
    for dir_path in dirs:
        os.makedirs(dir_path, exist_ok=True)
        console.print(f"[green]✓[/green] Created {dir_path}")
    
    # Create default config if it doesn't exist
    if not os.path.exists(DEFAULT_CONFIG_PATH) or force:
        default_config = """# E3 ComfyUI Agent Configuration

default_priority: 50
retry_limit: 2
poll_interval_ms: 1000

paths:
  jobs_processing: "comfyui_jobs/processing"
  jobs_finished: "comfyui_jobs/finished"
  database: "database/comfyui_agent.db"

comfyui:
  api_base_url: "http://127.0.0.1:8188"
  timeout_seconds: 300
"""
        with open(DEFAULT_CONFIG_PATH, 'w') as f:
            f.write(default_config)
        console.print(f"[green]✓[/green] Created {DEFAULT_CONFIG_PATH}")
    
    # Create default workflows config if it doesn't exist
    if not os.path.exists(DEFAULT_WORKFLOWS_PATH) or force:
        default_workflows = """# Workflow definitions

wf_realistic_portrait:
  template_path: "workflows/wf_realistic_portrait.json"
  required_inputs: ["prompt", "seed", "steps"]

wf_t2v_cinematic:
  template_path: "workflows/wf_t2v_cinematic.json"
  required_inputs: ["prompt", "seed", "duration"]

wf_tts_voice:
  template_path: "workflows/wf_tts_voice.json"
  required_inputs: ["text", "voice_model"]
"""
        with open(DEFAULT_WORKFLOWS_PATH, 'w') as f:
            f.write(default_workflows)
        console.print(f"[green]✓[/green] Created {DEFAULT_WORKFLOWS_PATH}")
    
    # Initialize database
    cfg, _, db_path = get_config_and_db()
    console.print(f"[green]✓[/green] Initialized database at {db_path}")
    
    console.print("\n[green]Initialization complete![/green]")
    console.print("\nNext steps:")
    console.print("1. Configure ComfyUI connection in comfyui_agent/config/global_config.yaml")
    console.print("2. Add workflow templates to workflows/ directory")
    console.print("3. Start the agent with: [cyan]e3 start[/cyan]")


if __name__ == "__main__":
    app()