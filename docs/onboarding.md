# E3 – Phase 1: ComfyUI Agent — Onboarding

**Scope:** This guide helps a new developer or LLM/agent get the ComfyUI Agent running locally, submit a test job, and see it complete with full DB tracking (including retries and run counts).  
**Project:** Ember 3 (E3) — ViSuReNa LLC

---

## 1) What is this?
The **ComfyUI Agent** is a local execution service that:
- Watches a `jobs/processing/` folder for YAML configs
- Enqueues them into **SQLite**
- Picks the next job by **priority** and executes it via **ComfyUI API**
- Writes outputs to `jobs/finished/` and logs metadata/errors in the DB
- Retries failed jobs according to retry limits

> DB is the **source of truth** for scheduling, retries, and run counts. The filesystem stores configs and outputs.

---

## 2) Core Concepts
- **Single ComfyUI instance** (always-on)
- **YAML config** per job (single responsibility)
- **Global priority queue** (lower number = higher priority; default 50)
- **DB tracking** for status, retries, run counts, timing, error traces
- **Two continuous loops:** Monitor (filesystem → DB) and Scheduler/Executor (DB → ComfyUI)

---

## 3) Folder Structure (Phase 1)
```
E3/
├─ comfyui_agent/
│  ├─ config/
│  │  ├─ global_config.yaml
│  │  └─ workflows.yaml
│  ├─ monitor.py
│  ├─ executor.py
│  ├─ queue_manager.py
│  ├─ db_manager.py
│  ├─ ui_server.py
│  ├─ utils/
│  └─ tests/
├─ jobs/
│  ├─ processing/
│  │  ├─ image/  video/  audio/  speech/  3d/
│  └─ finished/
│     ├─ image/  video/  audio/  speech/  3d/
└─ database/
   └─ comfyui_agent.db
```

---

## 4) Prereqs & Install
- **Python 3.10+**
- **pip** & **venv**
- **ComfyUI** running locally (default API `http://127.0.0.1:8188`)

```bash
# from project root (E3/)
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Minimal `comfyui_agent/config/global_config.yaml`:
```yaml
default_priority: 50
retry_limit: 2            # global default; can be overridden per job (DB column)
poll_interval_ms: 1000

paths:
  jobs_processing: "jobs/processing"
  jobs_finished: "jobs/finished"
  database: "database/comfyui_agent.db"

comfyui:
  api_base_url: "http://127.0.0.1:8188"
  timeout_seconds: 300
```

Example `comfyui_agent/config/workflows.yaml`:
```yaml
wf_realistic_portrait:
  template_path: "workflows/wf_realistic_portrait.json"
  required_inputs: ["prompt", "seed", "steps"]
```

---

## 5) Database — Required Schema
> Includes **retry** and **run count** so scheduling is fully DB-driven.

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_name TEXT NOT NULL UNIQUE,
    job_type TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    priority INTEGER DEFAULT 50,
    status TEXT CHECK(status IN ('pending','processing','done','failed')) NOT NULL,
    retries_attempted INTEGER DEFAULT 0,   -- number of retries used
    run_count INTEGER DEFAULT 0,           -- total executions (initial + retries)
    retry_limit INTEGER,                   -- optional per-job override; NULL -> use global
    start_time TEXT,
    end_time TEXT,
    duration REAL,
    error_trace TEXT,
    metadata TEXT,
    worker_id TEXT,
    lease_expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_priority ON jobs(status, priority);
CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(start_time);
```

**Notes**
- `retries_attempted` increments only when a run fails and we requeue.
- `run_count` increments **every time** we attempt execution (initial run and each retry).
- `retry_limit` (nullable) allows per-job override of global `retry_limit` from config.
- `config_name` is `UNIQUE` to avoid duplicate ingestion.

---

## 6) Running the Agent
You can run as one process (two async tasks) or two processes.

### Option A: Single process (recommended for dev)
```bash
python -m comfyui_agent.run   # starts Monitor + Scheduler/Executor
```

### Option B: Two CLIs (ops-friendly)
```bash
# terminal 1
python -m comfyui_agent.monitor

# terminal 2
python -m comfyui_agent.execute
```

Both options continuously poll:
- **Monitor** inserts/updates `pending` jobs in DB
- **Scheduler/Executor** leases the next job and runs it

---

## 7) Submit a Test Job (YAML)
Create a file at `jobs/processing/image/T2I_20250809123001_1_knight.yaml`:
```yaml
job_type: T2I
workflow_id: wf_realistic_portrait
priority: 20
inputs:
  prompt: "Ultra-realistic portrait of a medieval knight in rain, cinematic lighting"
  seed: 123456
  steps: 30
outputs:
  file_path: "jobs/finished/image/T2I_20250809123001_1_knight.png"
metadata:
  creator: "cli"
  version: "1.0"
```

Within ~1s, Monitor writes it to DB; Scheduler should pick and run it next.

---

## 8) Useful DB Queries

**Pending jobs:**
```sql
SELECT id, config_name, priority FROM jobs WHERE status='pending' ORDER BY priority, id;
```

**Currently processing:**
```sql
SELECT id, config_name, worker_id, lease_expires_at FROM jobs WHERE status='processing';
```

**Recently finished:**
```sql
SELECT id, config_name, duration FROM jobs WHERE status='done' ORDER BY end_time DESC LIMIT 20;
```

**Failures with last error:**
```sql
SELECT id, config_name, retries_attempted, run_count, error_trace
FROM jobs
WHERE status='failed'
ORDER BY end_time DESC;
```

**Jobs that exceeded retry limit (global=2 or per-job override):**
```sql
SELECT id, config_name, retries_attempted, COALESCE(retry_limit, 2) AS limit_used
FROM jobs
WHERE status='failed' AND retries_attempted >= COALESCE(retry_limit, 2);
```

**Bump priority (God Mode):**
```sql
UPDATE jobs SET priority=1 WHERE config_name='T2I_20250809123001_1_knight.yaml';
```

**Recover orphaned jobs (agent crash):**
```sql
UPDATE jobs
SET status='pending', worker_id=NULL, lease_expires_at=NULL
WHERE status='processing' AND lease_expires_at < CURRENT_TIMESTAMP;
```

---

## 9) How It Works (short)
1. **Monitor Loop** scans `jobs/processing/**.yaml` → validates → inserts as `pending`.
2. **Scheduler/Executor Loop** leases next job from DB (priority+FIFO) → calls ComfyUI API.
3. On success → write outputs, mark `done`. On failure → increment `run_count`, set `error_trace`:
   - if `retries_attempted < limit` → increment `retries_attempted`, requeue `pending`
   - else mark `failed`

> DB columns `retries_attempted` and `run_count` are the **single source of truth** for retry and attempt tracking.

---

## 10) CLI (optional)
Provide thin wrappers for common operations:
```bash
# add a job (ingest a file path)
e3 add jobs/processing/image/T2I_...yaml

# show queue
e3 queue ls

# set priority (God Mode)
e3 queue set-priority T2I_...yaml 1

# retry failed
e3 retry T2I_...yaml
```

---

## 11) Troubleshooting
- **Job not picked up:** Check DB status is `pending`; verify `poll_interval_ms`; ensure ComfyUI API is reachable.
- **Repeated failures:** Check `error_trace` in DB; confirm `workflow_id` exists in `workflows.yaml` and required inputs are present.
- **Paths/permissions:** Ensure `jobs/finished/*` exists and is writable.
- **Duplicate ingestion:** Ensure `config_name` is unique per YAML.

---

## 12) Next Steps
- Read **PRD.md** for deep design details.
- Read **PRFAQ.md** for vision and scope.
- Start writing unit tests in `comfyui_agent/tests/` (TDD-first).
