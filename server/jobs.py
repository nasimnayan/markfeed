"""Job manager: per-job working dirs on disk + an in-process single-worker queue.

Each conversion runs in an isolated subprocess (worker.py). Jobs are processed
one at a time (OCR is CPU-heavy). State lives on disk under jobs/<job_id>/ so it
survives server restarts and powers the "recent jobs" list; the in-memory
registry only caches the running subprocess handle.
"""

import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER_SCRIPT = PROJECT_ROOT / "worker.py"
JOBS_ROOT = PROJECT_ROOT / "jobs"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class JobManager:
    def __init__(self, jobs_root: Path = JOBS_ROOT) -> None:
        self.jobs_root = jobs_root
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._current: str | None = None  # job_id currently running

    # ----- creation -------------------------------------------------------
    def create_job(self, filename: str, file_bytes: bytes, options: dict) -> str:
        job_id = uuid4().hex
        job_dir = self.jobs_root / job_id
        job_dir.mkdir(parents=True)

        file_type = options["file_type"]
        input_name = "input.pdf" if file_type == "pdf" else "input.docx"
        (job_dir / input_name).write_bytes(file_bytes)

        job = {
            "job_id": job_id,
            "filename": filename,
            "file_type": file_type,
            "lang": options.get("lang", "ben+eng"),
            "dpi": options.get("dpi", 300),
            "use_layout": options.get("use_layout", False),
            "start_page": options.get("start_page", 0),
            "end_page": options.get("end_page"),
            "created_at": _now(),
        }
        (job_dir / "job.json").write_text(
            json.dumps(job, ensure_ascii=False), encoding="utf-8"
        )
        (job_dir / "progress.json").write_text(
            json.dumps({"status": "queued"}, ensure_ascii=False), encoding="utf-8"
        )

        self._queue.put_nowait(job_id)
        return job_id

    # ----- status ---------------------------------------------------------
    def _job_dir(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    def get_status(self, job_id: str) -> dict | None:
        job_dir = self._job_dir(job_id)
        job = _read_json(job_dir / "job.json")
        if job is None:
            return None
        progress = _read_json(job_dir / "progress.json") or {}
        error = _read_json(job_dir / "error.json")

        status = progress.get("status", "queued")
        out = {
            "job_id": job_id,
            "filename": job.get("filename"),
            "file_type": job.get("file_type"),
            "status": status,
            "done": progress.get("done", 0),
            "total": progress.get("total", 0),
            "created_at": job.get("created_at"),
            "updated_at": progress.get("updated_at"),
            "message": None,
            "suggest_retry_without_layout": False,
            "use_layout": job.get("use_layout", False),
        }
        if error:
            out["message"] = error.get("message")
            out["suggest_retry_without_layout"] = error.get(
                "suggest_retry_without_layout", False
            )
        return out

    def list_jobs(self) -> list[dict]:
        jobs = []
        for job_dir in self.jobs_root.iterdir():
            if not job_dir.is_dir():
                continue
            status = self.get_status(job_dir.name)
            if status:
                jobs.append(status)
        jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
        return jobs

    def get_job(self, job_id: str) -> dict | None:
        return _read_json(self._job_dir(job_id) / "job.json")

    # ----- background worker loop ----------------------------------------
    async def worker_loop(self) -> None:
        """Process queued jobs one at a time, each in an isolated subprocess."""
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_job(job_id)
            except Exception as exc:  # noqa: BLE001 — never let the loop die
                self._mark_crashed(job_id, f"Job runner error: {exc}")
            finally:
                self._current = None
                self._queue.task_done()

    async def _run_job(self, job_id: str) -> None:
        job_dir = self._job_dir(job_id)
        if not (job_dir / "job.json").exists():
            return  # job was deleted before it ran
        self._current = job_id

        import os

        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        proc = subprocess.Popen(
            [sys.executable, str(WORKER_SCRIPT), str(job_dir)],
            cwd=str(PROJECT_ROOT),
            env=env,
        )

        while proc.poll() is None:
            await asyncio.sleep(1.0)

        returncode = proc.returncode
        if returncode == 0:
            return  # worker wrote result.json + converted.md

        # Non-zero exit. If the worker caught the error it wrote error.json.
        if (job_dir / "error.json").exists():
            return  # status already reflects the error

        # No error.json => the process died abnormally (segfault / OOM / kill).
        self._mark_crashed(
            job_id,
            f"Worker process crashed unexpectedly (exit code {returncode}). "
            "This usually means a native crash in the layout-aware OCR "
            "(PP-StructureV3) pipeline.",
        )

    def _mark_crashed(self, job_id: str, message: str) -> None:
        job_dir = self._job_dir(job_id)
        if not job_dir.exists():
            return
        (job_dir / "error.json").write_text(
            json.dumps(
                {
                    "message": message,
                    "suggest_retry_without_layout": True,
                    "updated_at": _now(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (job_dir / "progress.json").write_text(
            json.dumps(
                {"status": "crashed", "message": message, "updated_at": _now()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
