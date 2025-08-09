# Ember 3 (E3) – PRFAQ
## Phase 1: ComfyUI Agent

## Press Release

**Date:** TBD  
**From:** ViSuReNa LLC  
**Subject:** Launch of Ember 3 – Phase 1: ComfyUI Agent

Seattle, WA — ViSuReNa proudly announces **Ember 3 (E3)**, the next evolution of its AI media generation ecosystem.  
E3 is designed as a multi-phase, modular system that automates the creation of AI-generated stories, music, audio, and videos for YouTube and beyond.  

**Phase 1** launches with the **ComfyUI Agent**, a dedicated execution engine that processes AI job configs through a single ComfyUI instance.  
This agent handles the detection, prioritization, execution, and logging of jobs, providing a foundation for scalability and future automation.

Key features of the ComfyUI Agent:
- **Unified Config Format** for all asset types (T2I, T2V, Speech, Audio, 3D, etc.).
- **Global Priority Queue** for optimized execution order.
- **Automatic Folder Monitoring** (`processing` → `finished`).
- **SQLite-Powered Job Tracking** for metadata, timing, and error logging.
- **Local Web UI** to monitor, reprioritize, and debug jobs in real-time.
- **TDD Compliance** for reliability and maintainability.

---

## FAQ

### 1. What problem does Phase 1 solve?
E3 Phase 1 addresses the execution bottleneck in AI media generation.  
Previously, jobs were run in large batches without fine-grained control or tracking.  
The ComfyUI Agent introduces:
- Single-job configs for easier debugging
- Global prioritized execution
- Automatic logging & error tracking
- Real-time UI for queue control

---

### 2. How does the ComfyUI Agent work?
- **Two Continuous Loops**:
  1. **Monitor Loop**: Watches a `processing` folder and writes valid configs into SQLite as `pending` jobs.
  2. **Scheduler/Executor Loop**: Continuously picks the highest-priority pending job from SQLite and executes it via ComfyUI API.
- **Folder Monitoring:** Watches `processing` subfolders for each media type (`image/`, `video/`, `audio/`, `speech/`, `3d/`).
- **Config Files:** Each YAML job file includes inputs, outputs, and priority (lower = higher priority, default = 50).
- **Execution:** The ComfyUI Agent calls the ComfyUI API with the mapped workflow template.
- **Lifecycle:** On success, the config moves to `finished/`; on failure, it retries (configurable), logs errors, and updates SQLite.
- **UI:** Local dashboard displays all jobs, priorities, errors, and performance metrics.

---

### 3. Why single configs instead of bulk jobs?
Single configs improve scalability, efficiency, debugging, and reproducibility.

---

### 4. How is priority handled?
Lower number = higher priority (1 = top priority, 50 = default).  
Jobs are executed in global priority order across all media types.  
God Mode pushes a job to the top of the queue without interrupting the current run.

---

### 5. How are failures handled?
Retries defined in `global_config.yaml`.  
Stack traces stored in SQLite for UI display.  
Failed jobs remain in `processing/` with status `failed` until retried manually.

---

### 6. How is data stored?
- **Config Files:** Remain in `finished/` for reproducibility.
- **Database:** Tracks metadata only—job type, config name, workflow ID, priority, status, retries, start/end times, duration, error trace, and optional metadata.

---

### 7. What is the role of ComfyUI?
The ComfyUI Agent runs against a single always-on ComfyUI instance.  
Jobs are triggered via API using workflow IDs mapped to pre-saved templates.

---

### 8. What can the UI do?
View queue, completed jobs, failed jobs; change job priority/order; view error details; retry failed jobs; with safeguards to prevent DB corruption.

---

### 9. What is the development approach?
TDD-first, small testable functions, unit tests for all modules.

---

### 10. What’s next for E3?
Future phases will introduce config generation, placement, multi-agent orchestration, and cloud execution.

---

## Example Config (YAML)

```yaml
job_type: T2I
workflow_id: wf_realistic_portrait
priority: 20
inputs:
  prompt: "Ultra-realistic portrait of a medieval knight in rain, cinematic lighting"
  seed: 123456
  steps: 30
outputs:
  file_path: "/finished/image/T2I_20250809123001_1_knight.png"
metadata:
  creator: "ComfyUI Agent"
  version: "1.0"
```
