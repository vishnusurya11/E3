# Audiobook CLI Automation Setup

## Overview
Automate the audiobook processing pipeline to run at regular intervals using Windows Task Scheduler or Python scheduler.

## Files Created

### 1. `audiobook_automation.bat`
Simple batch script for Task Scheduler integration.

### 2. `audiobook_scheduler.py`
Advanced Python scheduler with configurable settings and logging.

### 3. `config/automation_config.json`
Configuration file for customizing automation behavior.

---

## Option 1: Windows Task Scheduler (Recommended)

### Setup Steps:

#### 1. **Open Task Scheduler**
- Press `Win + R`, type `taskschd.msc`, press Enter

#### 2. **Create Basic Task**
- Click "Create Basic Task" in Actions panel
- **Name**: `Audiobook CLI Automation`
- **Description**: `Automated audiobook processing pipeline`

#### 3. **Set Trigger**
- **Trigger**: Daily
- **Start**: Today's date
- **Recur every**: 1 days
- **Repeat task every**: 5 minutes (configurable)
- **For a duration of**: Indefinitely

#### 4. **Set Action**
- **Action**: Start a program
- **Program/script**: `D:\Projects\pheonix\alpha\E3\audiobook_automation.bat`
- **Start in**: `D:\Projects\pheonix\alpha\E3`

#### 5. **Advanced Settings**
- Check "Run whether user is logged on or not"
- Check "Do not store password"
- Check "Run with highest privileges" (if needed)
- **If the task is already running**: Do not start a new instance

### 6. **Configure Output Capture**
To capture output to a specific location, modify the batch file:

```batch
REM Add this line before running Python:
python audiobook_agent/audiobook_cli.py >> logs/scheduled_output.log 2>&1
```

---

## Option 2: Python Scheduler

### Usage:
```bash
# Edit config/automation_config.json to set interval_minutes
python audiobook_scheduler.py
```

### Configuration:
Edit `config/automation_config.json`:
```json
{
  "interval_minutes": 5,     // Run every 5 minutes
  "log_file": "logs/batch_automation.log",
  "timeout_minutes": 60,     // Kill if CLI runs longer than 1 hour
  "verbose_output": true     // Include detailed logging
}
```

### Features:
- ✅ **Configurable intervals**
- ✅ **Comprehensive logging** with timestamps
- ✅ **Error handling** with timeout protection
- ✅ **Log rotation** to prevent huge files
- ✅ **Easy to stop** with Ctrl+C

---

## Option 3: Advanced Batch with Output Capture

### Enhanced Batch Script:
```batch
@echo off
cd /d "D:\Projects\pheonix\alpha\E3"
call .venv\Scripts\activate

REM Capture output to specific location
echo [%date% %time%] Starting audiobook CLI... >> logs/scheduled_runs.log
python audiobook_agent/audiobook_cli.py >> logs/scheduled_runs.log 2>&1
echo [%date% %time%] CLI completed with exit code %ERRORLEVEL% >> logs/scheduled_runs.log

deactivate
```

---

## Monitoring and Logs

### Log Files:
- **CLI logs**: `logs/audiobook.log` (from CLI itself)
- **Automation logs**: `logs/batch_automation.log` (from scheduler)
- **Scheduled runs**: `logs/scheduled_runs.log` (from batch script)

### Monitoring Commands:
```bash
# Watch real-time automation logs
tail -f logs/batch_automation.log

# Check recent CLI activity
tail -20 logs/audiobook.log

# View last scheduled run
tail -50 logs/scheduled_runs.log
```

---

## Troubleshooting

### Common Issues:

#### **Virtual Environment Issues**
- Ensure `.venv` exists and has correct Python installation
- Test manually: `cd D:\Projects\pheonix\alpha\E3 && .venv\Scripts\activate`

#### **Path Issues**
- Use full absolute paths in Task Scheduler
- Ensure "Start in" directory is set correctly

#### **Permission Issues**
- Run Task Scheduler as administrator if needed
- Check file/directory permissions

#### **CLI Hanging**
- The re-entry protection should prevent overlaps
- Check `logs/audiobook.log` for "STILL_PROCESSING" messages
- Increase timeout if needed

### Testing:
```bash
# Test batch script manually
audiobook_automation.bat

# Test Python scheduler manually  
python audiobook_scheduler.py
```

---

## Recommended Setup

1. **Use Windows Task Scheduler** with `audiobook_automation.bat`
2. **Set interval to 5 minutes** (configurable via Task Scheduler)
3. **Modify batch file** to capture output: `>> logs/scheduled_output.log 2>&1`
4. **Monitor logs** in `logs/` directory
5. **Enable log rotation** to prevent disk space issues

The automation is now ready for production use! 🚀