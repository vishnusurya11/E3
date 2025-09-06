# Ember 3 (E3) – PRFAQ
## Phase 1: ComfyUI Agent

**Date:** 2025-08-09  
**Owner:** ViSuReNa

---

## Press Release

Seattle, WA — ViSuReNa announces **Ember 3 (E3)**, a modular AI media generation system designed to automate the creation of images, video, audio, speech, and 3D assets. **Phase 1** delivers the **ComfyUI Agent**, a local execution engine that monitors a folder for YAML configs, queues them in SQLite, and executes them through a **single always-on ComfyUI instance** (via HTTP API at a configurable `comfyui.endpoint`).

**Highlights**
- Unified YAML configs across modalities (T2I, T2V, AUDIO, SPEECH, 3D).
- Global **priority queue** (lower number = higher priority; default 50).
- Two continuous loops: **Monitor** (filesystem→DB) and **Scheduler/Executor** (DB→ComfyUI).
- **SQLite logging** of status, timings, retries, and errors.
- Local **web UI** to view queue, change priority, retry failed jobs, and view errors.
- **TDD-first** codebase; tiny, single-responsibility functions; slim module layout.

This forms the foundation for later phases (config generation, placement, orchestration, cloud backends).

---

## FAQ

### What problem does Phase 1 solve?
Previous Ember iterations generated quality assets but lacked a robust, observable execution layer. Phase 1 introduces a **DB-backed scheduler**, **file-to-DB ingestion**, and a **UI** for control and debugging.

### How does it work?
- Drop a YAML config into `jobs/processing/<type>/`.  
- **Monitor** validates & inserts it into **SQLite** as `pending`.  
- **Scheduler/Executor** leases the next job (by priority & FIFO), calls ComfyUI via `comfyui.endpoint`, and writes outputs to `jobs/finished/<type>/`.  
- Status, timings, retries, and errors are logged in the DB and visible in the UI.

### Why one config per job?
It makes execution **scalable**, **traceable**, and **reproducible**, with clean failure isolation.

### How are priorities handled?
**Lower number = higher priority**. God Mode sets priority to `1`. The current job is never pre-empted; God Mode runs next.

### What happens on failure?
The job’s `run_count` increments; if under the (per-job or global) `retry_limit`, it’s requeued. On final failure it’s marked `failed` with full `error_trace` for UI display.

### What’s in the database?
`jobs` table with `config_name`, `job_type`, `workflow_id`, `priority`, `status`, `run_count`, `retries_attempted`, `retry_limit`, `start_time`, `end_time`, `duration`, `error_trace`, `metadata`, and leasing fields (`worker_id`, `lease_expires_at`).

### What is the ComfyUI requirement?
A **single always-on** ComfyUI instance reachable at `comfyui.endpoint` (full URL, e.g., `http://127.0.0.1:8188`).

### What is the development approach?
**TDD-first** with tiny, single-responsibility functions, full type hints, and CI that runs `pytest` + linters. Use **uv** for dependency management.

### What’s next for E3?
Config generation agents, placement/batching, multi-agent orchestration, combined workflows, and cloud execution backends.
