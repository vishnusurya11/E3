# WSL to Windows ComfyUI Connection Setup

## The Issue
You're running the E3 agent in WSL but ComfyUI is running on Windows. They can't connect because:
- WSL has its own network namespace
- `127.0.0.1` in WSL refers to WSL's localhost, not Windows
- Windows Firewall may block WSL connections

## Solution

### On Windows - Start ComfyUI with network access:

```cmd
# In your ComfyUI directory on Windows:
python main.py --listen 0.0.0.0 --port 8000
```

**Important**: The `--listen 0.0.0.0` flag makes ComfyUI accept connections from any network interface, including WSL.

### Windows Firewall Configuration

If ComfyUI still can't be reached, allow it through Windows Firewall:

1. Open Windows Defender Firewall with Advanced Security
2. Click "Inbound Rules" → "New Rule"
3. Choose "Port" → TCP → Specific local port: 8000
4. Allow the connection
5. Apply to all profiles (Domain, Private, Public)
6. Name it "ComfyUI WSL Access"

### Alternative: Run Everything in the Same Environment

#### Option A: Run both in Windows
```cmd
# Terminal 1 - Start ComfyUI (Windows)
cd C:\path\to\ComfyUI
python main.py --port 8000

# Terminal 2 - Run E3 Agent (Windows)
cd D:\Projects\pheonix\prod\E3\E3
python -m comfyui_agent.cli start --ui-port 8080
```

#### Option B: Run both in WSL
```bash
# Terminal 1 - Start ComfyUI (WSL)
cd /mnt/c/path/to/ComfyUI
python main.py --port 8000

# Terminal 2 - Run E3 Agent (WSL)
cd /mnt/d/Projects/pheonix/prod/E3/E3
python -m comfyui_agent.cli start --ui-port 8080
```

## Current Configuration

The config has been updated to use the Windows host IP: `172.23.144.1:8000`

To find your Windows IP from WSL:
```bash
ip route | grep default | awk '{print $3}'
```

## Testing the Connection

```bash
# Test if ComfyUI is reachable
curl http://172.23.144.1:8000/system_stats
```

If this works, the E3 agent will be able to connect to ComfyUI.