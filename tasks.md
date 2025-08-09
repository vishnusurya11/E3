# E3 – Phase 1: ComfyUI Agent — Function-Level Build Plan (TDD-First)

> **Contract:** Every task below must be completed with **TDD**. For each function/module:
> 1) **Write tests first** (unit tests + docstring expectations).  
> 2) **Run all tests** (they should fail).  
> 3) **Implement the minimal code** to pass.  
> 4) **Run all tests** (they must pass).  
> 5) **Refactor safely** (no behavior change).  
> 6) **Run all tests** again.  
> 7) **Update docs** (docstrings and Markdown) and commit.

Conventions (pip/Python standards):
- **One function = one responsibility**; keep functions small and pure when possible.
- **Docstrings** (Google/NumPy style) include: purpose, parameters, returns, raises, examples.
- **Naming:** `snake_case` for functions/vars, `CamelCase` for classes. Tests: `test_<module>_<function>_<scenario>.py`.
- **Typing:** Use type hints on all public functions.
- **Lint/Format:** `black`, `isort`, `flake8` (or ruff). CI must run `pytest -q` and linters on each commit.
- **Isolation:** No network/filesystem in pure unit tests; mock side-effects (HTTP, FS). Use temp dirs and in-memory DB where needed.

---

## 0) Repository Bootstrap & Scaffolding

- [ ] **Create folder tree**
  - [ ] `comfyui_agent/{config,utils,tests}`
  - [ ] `jobs/{processing/{image,video,audio,speech,3d},finished/{image,video,audio,speech,3d}}`
  - [ ] `database`, `docs`, `workflows`
- [ ] **Add toolchain**
  - [ ] `pyproject.toml` or `setup.cfg` (black/isort/flake8/pytest configs)
  - [ ] `requirements.txt` (fastapi/flask, uvicorn, pyyaml, watchdog, httpx/requests, pytest, coverage, typer/argparse)
- [ ] **Initialize CI** (GitHub Actions or similar): run linters + `pytest -q` on PRs

---

## 1) Configuration Loader

### 1.1 `utils/config_loader.py::load_global_config(path: str) -> dict`
- **Purpose:** Load and validate `global_config.yaml`, applying defaults.
- **Inputs:** `path` to YAML file.
- **Returns:** Dict with keys: `default_priority`, `retry_limit`, `poll_interval_ms`, `paths{jobs_processing, jobs_finished, database}`, `comfyui{api_base_url, timeout_seconds}`.
- **Raises:** `ValueError` on invalid YAML or missing critical keys.
- **Subtasks (TDD):**
  - [ ] Write tests:
    - [ ] Valid YAML → merged with defaults.
    - [ ] Missing optional fields → defaults applied.
    - [ ] Bad YAML → raises.
  - [ ] Implement minimal logic.
  - [ ] Run tests, refactor, re-run tests.
  - [ ] Update docstrings & docs.

### 1.2 `utils/config_loader.py::load_workflows(path: str) -> dict[str, dict]`
- **Purpose:** Load `workflows.yaml`, validate `template_path` and `required_inputs` for each workflow.
- **Inputs:** `path` to YAML.
- **Returns:** Dict keyed by workflow_id; values contain `template_path`, `required_inputs`.
- **Raises:** `ValueError` if a workflow entry is invalid.
- **Subtasks (TDD):**
  - [ ] Tests: happy path; missing template_path; missing required_inputs; empty YAML.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 2) Path & File Utilities

### 2.1 `utils/file_utils.py::ensure_directories(paths: dict) -> None`
- **Purpose:** Create directories in `paths` if missing (idempotent).
- **Inputs:** `paths` mapping (e.g., from global config).
- **Returns:** None.
- **Subtasks (TDD):**
  - [ ] Tests: creates missing dirs; no-op when present.
  - [ ] Implement, run tests, refactor, re-run, document.

### 2.2 `utils/file_utils.py::list_yaml_under(root: str, *, media_types: list[str] = None) -> list[str]`
- **Purpose:** List absolute paths of `.yaml` files under `root` (optionally filter by subfolders `image/`, `video/`, etc.).
- **Inputs:** `root`, optional `media_types`.
- **Returns:** List of absolute file paths.
- **Subtasks (TDD):**
  - [ ] Tests: returns only YAMLs; ignores non-YAMLs; respects subfolder filter.
  - [ ] Implement, run tests, refactor, re-run, document.

### 2.3 `utils/file_utils.py::safe_move(src: str, dst: str) -> None`
- **Purpose:** Atomic file move using temp+rename; creates dst dirs as needed.
- **Inputs:** `src`, `dst`.
- **Returns:** None.
- **Subtasks (TDD):**
  - [ ] Tests: moves file; creates destination tree; handles existing dst dir.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 3) Validation Utilities (Pure)

### 3.1 `utils/validation.py::parse_config_name(filename: str) -> dict`
- **Purpose:** Parse and validate `TYPE_YYYYMMDDHHMMSS_X_jobname.yaml`.
- **Inputs:** `filename` (basename or full path).
- **Returns:** `{job_type, timestamp:str, index:int, jobname:str}`.
- **Raises:** `ValueError` on mismatch.
- **Subtasks (TDD):**
  - [ ] Tests: valid names; invalid type; malformed timestamp; non-integer X.
  - [ ] Implement, run tests, refactor, re-run, document.

### 3.2 `utils/validation.py::validate_config_schema(cfg: dict, workflows: dict) -> None`
- **Purpose:** Ensure required fields exist and values are sane.
- **Inputs:** `cfg`, `workflows` mapping.
- **Checks:** `job_type`, `workflow_id` in `workflows`, `inputs` keys include `required_inputs`, `outputs.file_path`, `priority` int (default 50, clamp 1–999).
- **Returns:** None (raises on error).
- **Subtasks (TDD):**
  - [ ] Tests: missing fields; bad workflow_id; missing required_inputs; invalid priority.
  - [ ] Implement, run tests, refactor, re-run, document.

### 3.3 `utils/validation.py::normalize_config(cfg: dict, defaults: dict) -> dict`
- **Purpose:** Apply default values (priority, retry_limit) and normalize types.
- **Inputs:** `cfg`, `defaults` from global config.
- **Returns:** Normalized `cfg` dict.
- **Subtasks (TDD):**
  - [ ] Tests: fills priority/retry_limit when missing; preserves provided values.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 4) Database Manager (SQLite)

### 4.1 `db_manager.py::init_db(db_path: str) -> None`
- **Purpose:** Create schema and indices; idempotent.
- **Schema includes:** `run_count`, `retries_attempted`, `retry_limit`, `worker_id`, `lease_expires_at`.
- **Subtasks (TDD):**
  - [ ] Tests: creates tables; second call no error; indices exist.
  - [ ] Implement, run tests, refactor, re-run, document.

### 4.2 `db_manager.py::upsert_job(row: dict) -> int`
- **Purpose:** Insert or update job by `config_name` (UNIQUE).
- **Inputs:** canonical row fields (`config_name`, `job_type`, `workflow_id`, `priority`, `status`, etc.).
- **Returns:** Job `id`.
- **Rules:** Do **not** regress completed jobs; if exists with `done/failed`, ignore or update only metadata.
- **Subtasks (TDD):**
  - [ ] Tests: insert new; duplicate ingestion does not duplicate; no regression of terminal states.
  - [ ] Implement, run tests, refactor, re-run, document.

### 4.3 `db_manager.py::lease_next_job(worker_id: str, lease_seconds: int) -> dict | None`
- **Purpose:** Atomically pick the next `pending` job (priority ASC, id ASC), mark as `processing`, set lease.
- **Returns:** Leased job row or `None` if none available.
- **Subtasks (TDD):**
  - [ ] Tests: correct ordering; only one lease under simulated concurrency; none pending → None.
  - [ ] Implement, run tests, refactor, re-run, document.

### 4.4 `db_manager.py::complete_job(id: int, *, success: bool, updates: dict) -> None`
- **Purpose:** Finalize job result.
- **On success:** `status='done'`, set `end_time`, `duration`, `metadata`.
- **On failure:** increment `run_count`, `retries_attempted`; set `error_trace`; if retries left → `pending` else `failed`.
- **Subtasks (TDD):**
  - [ ] Tests: transitions valid; retries obey limit; counters updated.
  - [ ] Implement, run tests, refactor, re-run, document.

### 4.5 `db_manager.py::recover_orphans(now: datetime) -> int`
- **Purpose:** Requeue jobs with expired leases.
- **Returns:** number of jobs recovered.
- **Subtasks (TDD):**
  - [ ] Tests: jobs with lease_expires_at < now → `pending`; others untouched.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 5) ComfyUI Client

### 5.1 `executor.py::build_payload(workflow_id: str, inputs: dict, workflows: dict) -> dict`
- **Purpose:** Map `inputs` to the template defined by `workflows[workflow_id]`; ensure required inputs present.
- **Returns:** API payload.
- **Subtasks (TDD):**
  - [ ] Tests: required inputs enforced; extra inputs ignored or passed through as design dictates.
  - [ ] Implement, run tests, refactor, re-run, document.

### 5.2 `executor.py::invoke_comfyui(api_base_url: str, payload: dict, timeout: int) -> dict`
- **Purpose:** POST/WS to ComfyUI; return structured result (mock in tests).
- **Raises:** `RuntimeError` on HTTP/client errors or invalid response shape.
- **Subtasks (TDD):**
  - [ ] Tests: happy path; timeout; malformed response.
  - [ ] Implement, run tests, refactor, re-run, document.

### 5.3 `executor.py::write_outputs(result: dict, dest_paths: dict) -> dict`
- **Purpose:** Persist generated artifacts to disk (images/videos/audio).
- **Returns:** Metadata (`{ "saved": [paths], "bytes": n, "hash": "...", ... }`).
- **Subtasks (TDD):**
  - [ ] Tests: writes expected files; handles missing dirs via `safe_move` creation.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 6) Queue Manager (In-Memory)

### 6.1 `queue_manager.py::should_run_next(current_busy: bool) -> bool`
- **Purpose:** Gate for single-GPU sequential execution.
- **Subtasks (TDD):**
  - [ ] Tests: returns False when busy; True when idle.
  - [ ] Implement, run tests, refactor, re-run, document.

### 6.2 `queue_manager.py::apply_god_mode(db, config_name: str) -> None`
- **Purpose:** Set priority to `1` for a job by `config_name`.
- **Subtasks (TDD):**
  - [ ] Tests: updates row; invalid name → no-op/raises per design.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 7) Monitor Service (FS → DB)

### 7.1 `monitor.py::scan_once(cfg: dict, workflows: dict, db) -> list[dict]`
- **Purpose:** Detect new YAML files, load, validate, normalize, and upsert into DB as `pending`.
- **Returns:** List of `{path, status: accepted|rejected, reason?}` for logging.
- **Subtasks (TDD):**
  - [ ] Tests: detects only YAML; rejects invalid schema; handles duplicates gracefully.
  - [ ] Implement, run tests, refactor, re-run, document.

### 7.2 `monitor.py::run_monitor_loop(cfg: dict, workflows: dict, db, stop_event) -> None`
- **Purpose:** Continuous loop: `scan_once` then sleep `poll_interval_ms`.
- **Subtasks (TDD):**
  - [ ] Tests: single-iteration with fake `stop_event`.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 8) Scheduler/Executor Service (DB → ComfyUI)

### 8.1 `executor.py::execute_job(job: dict, cfg: dict, workflows: dict, db) -> None`
- **Purpose:** End-to-end execution: build payload → invoke ComfyUI → write outputs → update DB → move YAML to finished.
- **Subtasks (TDD):**
  - [ ] Tests: happy path (mock HTTP + FS); failure path sets error & retries.
  - [ ] Implement, run tests, refactor, re-run, document.

### 8.2 `executor.py::run_once(cfg: dict, workflows: dict, db, worker_id: str) -> bool`
- **Purpose:** Orphan recovery → `lease_next_job` → if a job, increment `run_count`, execute it.
- **Returns:** True if work executed; False if idle.
- **Subtasks (TDD):**
  - [ ] Tests: returns False when no job; True when job leased.
  - [ ] Implement, run tests, refactor, re-run, document.

### 8.3 `executor.py::run_loop(cfg: dict, workflows: dict, db, worker_id: str, stop_event) -> None`
- **Purpose:** Continuous loop: `run_once` else sleep `poll_interval_ms`.
- **Subtasks (TDD):**
  - [ ] Tests: loop honors `stop_event`.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 9) Logging

### 9.1 `utils/logger.py::get_logger(name: str) -> logging.Logger`
- **Purpose:** Return a structured logger configured for the project.
- **Subtasks (TDD):**
  - [ ] Tests: logger emits expected fields; no duplicate handlers on repeated calls.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 10) UI Backend (FastAPI suggested)

### 10.1 `ui_server.py::list_queue(status: str | None = None) -> list[dict]`
- **Purpose:** Return jobs, optionally filtered by status.
- **Subtasks (TDD):**
  - [ ] Tests: proper filtering; JSON shape stable.
  - [ ] Implement, run tests, refactor, re-run, document.

### 10.2 `ui_server.py::set_priority(config_name: str, priority: int) -> dict`
- **Purpose:** Update job priority (bounds check; transaction).
- **Subtasks (TDD):**
  - [ ] Tests: rejects invalid; accepts valid, persists.
  - [ ] Implement, run tests, refactor, re-run, document.

### 10.3 `ui_server.py::retry_job(config_name: str) -> dict`
- **Purpose:** If job is `failed`, set to `pending` for re-execution; keep counters (optionally append to error history).
- **Subtasks (TDD):**
  - [ ] Tests: only failed can be retried; idempotent behavior.
  - [ ] Implement, run tests, refactor, re-run, document.

### 10.4 `ui_server.py::job_details(config_name: str) -> dict`
- **Purpose:** Return full job record including error trace, timings, metadata.
- **Subtasks (TDD):**
  - [ ] Tests: 404 if not exists; happy path returns all fields.
  - [ ] Implement, run tests, refactor, re-run, document.

### 10.5 `ui_server.py::god_mode(config_name: str) -> dict`
- **Purpose:** Set priority to `1` for the job.
- **Subtasks (TDD):**
  - [ ] Tests: priority updated; persisted; invalid name handled.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 11) UI Frontend (minimal SPA)

### 11.1 `ui_frontend/index.html` + `app.js` (or React if desired)
- **Views:** Queue, Processing, Done, Failed.
- **Actions:** change priority, retry, god mode.
- **Auto-refresh:** poll every N seconds.
- **Subtasks (TDD/QA):**
  - [ ] Serve static files via backend.
  - [ ] Basic integration tests (e2e happy path) or manual QA script.
  - [ ] Accessibility pass (labels, keyboard nav).

---

## 12) CLI Helpers (optional)

### 12.1 `cli.py::main()` with subcommands
- **Commands:**
  - `e3 monitor --once|--loop`
  - `e3 run --once|--loop`
  - `e3 queue ls [status]`
  - `e3 queue set-priority <config_name> <n>`
  - `e3 retry <config_name>`
- **Subtasks (TDD):**
  - [ ] Tests: argparse wiring; handler calls; error on bad args.
  - [ ] Implement, run tests, refactor, re-run, document.

---

## 13) End-to-End Smoke (Local)

- [ ] Start ComfyUI locally.
- [ ] Run monitor + executor loop (single process or two CLIs).
- [ ] Drop example YAML under `jobs/processing/image/…`.
- [ ] Verify output in `jobs/finished/image/…`.
- [ ] Verify DB: `status='done'`, `run_count=1`, `retries_attempted=0`.
- [ ] Record timings and confirm UI displays them.

---

## 14) Hardening & Guardrails

- [ ] Add DB constraints/enums; enforce priority bounds.
- [ ] Configurable lease timeout; test orphan recovery.
- [ ] Preflight: check output path writable before leasing (optional).
- [ ] Backpressure: warn if `pending` exceeds threshold; UI banner.

---

## 15) Documentation & Samples

- [ ] Root `README.md` quick start.
- [ ] Update `docs/README_docs.md` index and links.
- [ ] Add sample `workflows/*.json` placeholders and example YAML jobs.
- [ ] Changelog entry and version bump.

---

## Templates

**Docstring template (Google style):**
```python
def example(arg1: str, arg2: int) -> bool:
    """One-line summary in imperative mood.

    Detailed description explaining what the function does and its single responsibility.

    Args:
        arg1: What it represents and any constraints.
        arg2: What it represents and valid range/meaning.

    Returns:
        True if <condition>; otherwise False.

    Raises:
        ValueError: If inputs are invalid.
        RuntimeError: On unexpected runtime errors.

    Examples:
        >>> example("x", 1)
        True
    """
    ...
```

**Test naming example:**
```python
# tests/test_validation_parse_config_name_valid.py
def test_validation_parse_config_name_valid_minimal():
    ...
```

**CI command examples:**
```bash
pytest -q
coverage run -m pytest && coverage report -m
black --check . && isort --check-only . && flake8 .
```

---

### Acceptance Criteria (Global)
- Every function listed is implemented with TDD and has tests proving behavior.
- All unit tests and linters pass locally and in CI.
- Minimal e2e smoke succeeds (one happy path job end-to-end).
- UI can display queue, change priority, retry a failed job, and show error traces.
