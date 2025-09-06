# Ember 3 (E3) – Phase 1: ComfyUI Agent
**Author:** ViSuReNa LLC  
**Date:** TBD  
**Version:** 1.0

---

## 1. Overview
The **ComfyUI Agent** is the first module of **Ember 3 (E3)**—a scalable AI media generation pipeline in the ViSuReNa ecosystem. Phase 1 focuses exclusively on the **execution layer**, which detects, prioritizes, and processes job configs through a single always-running ComfyUI instance.

Future phases (config generation, placement/orchestration, combined workflows) will be separate modules with their own databases and dashboards.

---

## 2. Goals and Non-Goals

### Goals
- Monitor designated folders for incoming job configs.
- Execute each config via **ComfyUI API** using **pre-saved workflow templates** (by `workflow_id`).
- Maintain a **global priority queue** across all asset types.
- Log metadata and errors in **SQLite**.
- Provide a **local web UI** for job monitoring, priority adjustments, retries.
- Implement **TDD-first** development (small, single-responsibility functions, unit tests).
- Use **uv** for env/deps.

### Non-Goals
- Config generation or placement logic (Phase 2+).
- Parallel processing or multi-GPU support (Phase 1 is sequential).
- Cloud/remote execution.
- CPU/GPU performance tracking.

---

## 3. Functional Requirements

### 3.1 Folder Monitoring
- Watch `jobs/processing/` and subfolders: `image/`, `video/`, `audio/`, `speech/`, `3d/`.
- On successful completion, move configs to `jobs/finished/<type>/`.
- Provide **file-level isolation** (single config per job) to improve debuggability and reproducibility.

### 3.2 Config Format (YAML)
- **Naming convention:** `TYPE_YYYYMMDDHHMMSS_X_jobname.yaml`
  - `TYPE` ∈ {`T2I`, `T2V`, `SPEECH`, `AUDIO`, `3D`, …}
  - `X` = index within a multi-item job (e.g., 1..20)
- **Fields:**
  - `job_type` (enum): `T2I`, `T2V`, `SPEECH`, `AUDIO`, `3D`, …
  - `workflow_id` (string): maps to pre-saved ComfyUI template
  - `priority` (int): **lower = higher priority** (default: `50`)
  - `inputs` (object): prompt, seed, steps, parameters needed by the workflow
  - `outputs` (object): desired output path(s), filename, metadata
  - `metadata` (object, optional): arbitrary JSON-serializable extras (creator, version, notes)

**Example:**
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
  creator: "ComfyUI Agent"
  version: "1.0"
```

### 3.3 Execution Engine
- Single **always-on** ComfyUI instance.
- The agent calls ComfyUI API with `workflow_id` + `inputs`.
- Output artifacts are written to `jobs/finished/<type>/...` and paths recorded in DB.

### 3.4 Queue Management
- **Global queue** across all media types.
- Ordering:
  1. **Priority** (ascending; lower runs first; default = 50)
  2. **FIFO** within same priority (by `start_time` or insertion order)
- **God Mode:** push specified job to the **top of the queue** (without interrupting the currently running job).

### 3.5 Database Logging (SQLite)
- Store job metadata, status, timings, retries, and error traces.
- **Note:** Config files themselves are **not** stored in DB (they live in `jobs/finished/`).

### 3.6 UI Requirements
- Local web UI:
  - View **Queue / In-Progress / Completed / Failed**
  - Change **priority/order** safely (guardrails to prevent DB corruption)
  - **Retry** failed jobs
  - View **error details** (stack trace) inline
  - Auto-refresh (polling or websockets)

### 3.7 Error Handling
- Global retry count from `config/global_config.yaml`.
- On error: increment retry counter, requeue (until limit), then mark `failed` and persist stack trace.
- Failed configs remain in `processing/` for manual review and UI retry.

---

## 4. Non-Functional Requirements

### 4.1 Performance
- Sequential execution (single GPU).
- Minimize ComfyUI reload churn by honoring queue priority (grouping similar workflows naturally via priorities if desired).

### 4.2 Maintainability
- **Single-responsibility** functions with clear I/O.
- Unit tests on all public functions; run tests on each change.
- Configurable paths and API endpoints via `config/global_config.yaml`.

### 4.3 Reliability
- Queue state and DB persist across restarts.
- Idempotent processing (avoid double-runs on accidental restarts).

### 4.4 Security (Local Scope)
- Localhost UI only by default.
- Future: optional auth if remote access is enabled.

### 4.5 Developer Workflow
- Use **uv venv**, **uv pip**, `pytest`, linters; always update
- **README.md** and **tasks.md** when tasks change.

---

## 5. System Architecture

### 5.1 ASCII Diagram
```
        ┌──────────────────────┐
        │  jobs/processing/    │
        │  (image/video/...)   │
        └─────────┬────────────┘
                  │
                  ▼
        ┌──────────────────────┐
        │ Folder Monitor       │
        └─────────┬────────────┘
                  │
                  ▼
        ┌──────────────────────┐
        │ Queue Manager        │
        │ (priority, god mode) │
        └─────────┬────────────┘
                  │
                  ▼
        ┌──────────────────────┐
        │ ComfyUI Agent        │
        │ (API call, workflow) │
        └─────────┬────────────┘
                  │
        ┌─────────▼──────────┐
        │ ComfyUI Instance   │
        └─────────┬──────────┘
                  │
          Success │ Failure
                  ▼
        ┌──────────────────────┐
        │ jobs/finished/       │
        │   + SQLite DB log    │
        └──────────────────────┘
```

### 5.2 Components
- **Folder Monitor:** watches filesystem, validates YAML, inserts job row (`pending`) in DB.
- **Queue Manager:** computes next job (priority+FIFO), supports God Mode.
- **Executor (ComfyUI Agent):** calls ComfyUI API, handles success/failure, moves files.
- **DB Manager:** CRUD on jobs table, transactional updates.
- **UI Server:** presents state, applies safe mutations (priority/order), exposes retry.

---

## 6. Data Model (SQLite)

### 6.1 Schema
```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_name TEXT NOT NULL,
    job_type TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    priority INTEGER DEFAULT 50,
    status TEXT CHECK(status IN ('pending','processing','done','failed')) NOT NULL,
    retries_attempted INTEGER DEFAULT 0,
    start_time TEXT,
    end_time TEXT,
    duration REAL,
    error_trace TEXT,
    metadata TEXT
);

CREATE INDEX idx_jobs_status_priority ON jobs(status, priority);
CREATE INDEX idx_jobs_started ON jobs(start_time);
```

**Status lifecycle:** `pending` → `processing` → (`done` | `failed`)

**Note on metadata:** JSON string (e.g., output paths, file hashes, job notes).

---

## 7. Workflow Steps

### 7.1 Monitoring & Triggering Design

The ComfyUI Agent operates continuously with two cooperating loops (can be threads or separate processes):

1. **Monitor Loop**:
   - Watches `jobs/processing/<type>/` for new YAML configs.
   - Validates and inserts them into SQLite with `status='pending'`.
   - Uses unique `config_name` to avoid duplicates.

2. **Scheduler/Executor Loop**:
   - Checks for idle state.
   - Selects next job from SQLite using:
     ```sql
     SELECT * FROM jobs
     WHERE status='pending'
     ORDER BY priority ASC, id ASC
     LIMIT 1;
     ```
   - Marks job as `processing` with lease info to prevent duplicate runs.
   - Executes job via ComfyUI API.
   - Updates job to `done` or `failed`.

**Leasing & Recovery**:
- Each job in `processing` gets a lease expiration timestamp.
- On startup or periodically, expired leases are reset to `pending`.

**God Mode**:
- Priority is adjusted to a lower number (higher priority) via UI/CLI.
- No preemption—current job completes before God Mode job starts.

1. **Detect:** Folder Monitor detects a new YAML under `jobs/processing/<type>/`.
2. **Validate:** Validate structure (required fields, known `job_type`, known `workflow_id`, sane `priority`).
3. **Persist (pending):** Insert into `jobs` with `status='pending'`, `priority`, `workflow_id`, etc.
4. **Select:** Queue Manager selects next job: lowest `priority`, FIFO within same priority.
5. **Execute:** Executor calls ComfyUI API for `workflow_id` with provided `inputs`.
6. **Success Path:**
   - Write outputs to `jobs/finished/<type>/...`
   - Update DB to `done`, set `start_time`, `end_time`, `duration`, persist `metadata` (e.g., output path).
7. **Failure Path:**
   - Capture stack trace.
   - Increment `retries_attempted`; if `< retry_limit`, requeue; else mark `failed`.
8. **UI Visibility:** UI shows current queue, progress, results, and failures with error details.
9. **Manual Controls:** UI can adjust priority/order and trigger retries (with guardrails).

---

## 8. Error Handling & Observability
- **Global retry**: `config/global_config.yaml` (e.g., `retry_limit: 2`).
- **Error storage**: full stack trace in `error_trace` (for UI).
- **Safeguards**:
  - Atomic DB updates around state transitions.
  - File move operations resilient to partial failures (temp + rename).

---

## 9. Directory Structure (Annotated)

```
E3/
│
├── comfyui_agent/                     # Phase 1: ComfyUI Agent
│   ├── monitor.py                     # Folder monitoring logic
│   ├── executor.py                    # API calls to ComfyUI
│   ├── queue_manager.py               # Priority, god mode, ordering
│   ├── db_manager.py                  # SQLite ops
│   ├── ui_server.py                   # Local web UI backend
│   ├── config/
│   │   ├── global_config.yaml         # Retry limit, default priority, API URL, paths
│   │   └── workflows.yaml             # Workflow ID → template mapping
│   ├── tests/                         # Unit tests (TDD)
│   │   ├── test_monitor.py
│   │   ├── test_executor.py
│   │   ├── test_queue_manager.py
│   │   ├── test_db_manager.py
│   │   └── test_validation.py
│   └── utils/                         # Helpers
│       ├── logger.py
│       ├── file_utils.py
│       └── validation.py
│
├── jobs/
│   ├── processing/                    # Incoming jobs
│   │   ├── image/
│   │   ├── video/
│   │   ├── audio/
│   │   ├── speech/
│   │   └── 3d/
│   └── finished/                      # Completed jobs
│       ├── image/
│       ├── video/
│       ├── audio/
│       ├── speech/
│       └── 3d/
│
├── docs/                              # Documentation
│   ├── PRFAQ.md
│   ├── PRD.md
│   └── onboarding.md
│
└── database/
    └── comfyui_agent.db               # Phase 1 DB

# Future Phase: Config Generation Agent
# Future Phase: Placement/Batching Engine
# Future Phase: Multi-Agent Orchestration
# Future Phase: Combined Workflow Manager
```

---

## 10. Configuration Files

### 10.1 `config/global_config.yaml` (example)
```yaml
default_priority: 50
retry_limit: 2
poll_interval_ms: 1000

paths:
  jobs_processing: "jobs/processing"
  jobs_finished: "jobs/finished"
  database: "database/comfyui_agent.db"

comfyui:
  api_base_url: "http://127.0.0.1:8188"
  timeout_seconds: 300
```

### 10.2 `config/workflows.yaml` (example)
```yaml
wf_realistic_portrait:
  template_path: "workflows/wf_realistic_portrait.json"
  required_inputs: ["prompt", "seed", "steps"]

wf_t2v_cinematic_shot:
  template_path: "workflows/wf_t2v_cinematic_shot.json"
  required_inputs: ["prompt", "seed"]

wf_tts_clean_voice:
  template_path: "workflows/wf_tts_clean_voice.json"
  required_inputs: ["text"]
```

---

## 11. Testing Strategy (TDD)

**Principles**
- One function = one responsibility.
- Deterministic I/O; isolate side-effects.
- Mock ComfyUI API in tests; never require GPU for unit tests.

**Naming**
- `tests/test_<module>_<function>_<scenario>.py`

**Coverage**
- Folder detection & YAML parsing
- Validation (required fields, workflow exists, sane values)
- Queue ordering (priority, FIFO)
- Executor happy-path & error-path (API mocks)
- DB writes (transactions, state transitions)
- Retry logic & limits
- UI endpoints (if applicable)

**Sample Test**
```python
def test_queue_manager_orders_by_priority_and_fifo():
    jobs = [
        {"id": 1, "priority": 50, "insert_seq": 1},
        {"id": 2, "priority": 10, "insert_seq": 2},
        {"id": 3, "priority": 10, "insert_seq": 3},
        {"id": 4, "priority": 20, "insert_seq": 4},
    ]
    ordered = sort_jobs(jobs)  # lowest priority first, FIFO within priority
    assert [j["id"] for j in ordered] == [2, 3, 4, 1]
```

---

## 12. Future Integration Points
- **Config Generation Agent (Phase 2):** LLM/agent creates YAML configs.
- **Placement/Batching Engine (Phase 2):** Intelligent placement & batching strategy.
- **Multi-Agent Orchestration (Phase 3):** Distributed workers and scheduling.
- **Combined Workflow Manager (Phase 3):** Chaining T2I → T2V → TTS → SFX, etc.
- **Cloud Execution Backend (Phase 4):** Remote GPU fleets, multi-tenant scaling.

---

## 13. Acceptance Criteria
- Agent detects, validates, enqueues, and executes single-job YAML configs.
- Maintains a global priority queue (lower number = higher priority; default 50).
- Writes outputs to finished folder and logs metadata/errors in SQLite.
- UI shows queue and results; supports safe priority/order edits and retries.
- Unit tests cover the core modules; all tests pass locally.

---

## 14. Risks & Mitigations
- **Disk/Path errors:** Use atomic moves; verify paths exist; configurable paths in global config.
- **DB corruption risk:** Use transactions; constrain status values; UI guardrails.
- **Unexpected ComfyUI responses:** Strict schema for inputs; robust error capture; timeouts.
- **Large files/slow runs:** Clear timeouts; visible progress in UI (Phase 1 minimal polling).
