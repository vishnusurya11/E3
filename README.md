# E3 ComfyUI Agent

Monitors folders for YAML configs → Queues in SQLite → Executes via ComfyUI API → Saves outputs.

## Prerequisites
- Python 3.9+
- ComfyUI running at http://127.0.0.1:8000
- uv package manager: `pip install uv`

## Windows Setup (Command Prompt)
```cmd
# 1. Clean up old venv if exists
rmdir /s /q .venv

# 2. Create new virtual environment
uv venv

# 3. Activate venv (Windows)
.venv\Scripts\activate

# 4. Install requirements
uv pip install -r requirements.txt

# 5. Install package
uv pip install -e .

# 6. Initialize database
python -c "from comfyui_agent.db_manager import init_db; init_db('database/comfyui_agent.db')"
```

## Linux/WSL Setup
```bash
# Create and activate venv
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -e .
python -c "from comfyui_agent.db_manager import init_db; init_db('database/comfyui_agent.db')"
```

## Start ComfyUI (Required)
```cmd
# In your ComfyUI directory:
python main.py --port 8000
```

## Run E3 Agent

### Windows (Command Prompt)
```cmd
# Make sure venv is activated first!
.venv\Scripts\activate

# Start all services:
python -m comfyui_agent.cli start --ui-port 8080

# Or run separately:
python -m comfyui_agent.cli monitor    # Terminal 1: Monitor
python -m comfyui_agent.cli run        # Terminal 2: Executor
python -m comfyui_agent.ui_server 8080 # Terminal 3: Web UI
```

### Linux/WSL
```bash
source .venv/bin/activate
python -m comfyui_agent.cli start --ui-port 8080
```

## Submit Job
Copy a sample YAML to processing folder:

**Windows:**
```cmd
copy samples\test_job_t2i.yaml jobs\processing\image\
```

**Linux/WSL:**
```bash
cp samples/test_job_t2i.yaml jobs/processing/image/
```

The system will automatically:
1. Detect the file
2. Queue it in database
3. Send to ComfyUI
4. Save output to `jobs/finished/image/`

## Web UI
Open http://localhost:8080 to:
- View job queue
- See completed/failed jobs
- Retry failed jobs
- Adjust priorities

## Troubleshooting

### "Connection refused" error
- Make sure ComfyUI is running: `python main.py --port 8000`
- Check the port in `comfyui_agent/config/global_config.yaml`

### "Access denied" on Windows
- Close any programs using the .venv folder
- Run `rmdir /s /q .venv` to clean up
- Try creating venv again

### WSL to Windows ComfyUI
If running E3 in WSL but ComfyUI on Windows:
- Start ComfyUI with: `python main.py --listen 0.0.0.0 --port 8000`
- See WSL_COMFYUI_SETUP.md for details