"""Job manager: per-job working dirs on disk + an in-process single-worker queue.

Each conversion runs in an isolated subprocess (worker.py). Jobs are processed
one at a time (OCR is CPU-heavy). State lives on disk under jobs/<job_id>/ so it
survives server restarts and powers the "recent jobs" list; the in-memory
registry only caches the running subprocess handle.
"""

import asyncio
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKER_SCRIPT = PROJECT_ROOT / "worker.py"
JOBS_ROOT = PROJECT_ROOT / "jobs"

# Recent-conversions history is capped: only the newest MAX_HISTORY jobs are kept
# on disk. Older ones are deleted automatically when a new job is created, so the
# machine never accumulates conversions forever.
MAX_HISTORY = 10


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
        input_name = f"input.{file_type}"  # pdf / docx / csv / xls / xlsx
        (job_dir / input_name).write_bytes(file_bytes)

        job = {
            "job_id": job_id,
            "filename": filename,
            "file_type": file_type,
            "lang": options.get("lang", "ben+eng"),
            "dpi": options.get("dpi", 300),
            "use_layout": options.get("use_layout", False),
            "preprocess": options.get("preprocess", True),
            "make_searchable": options.get("make_searchable", False),
            "gen_toc": options.get("gen_toc", False),
            "preset": options.get("preset"),
            "start_page": options.get("start_page", 0),
            "end_page": options.get("end_page"),
            "batch_id": options.get("batch_id"),
            "created_at": _now(),
        }
        (job_dir / "job.json").write_text(
            json.dumps(job, ensure_ascii=False), encoding="utf-8"
        )
        (job_dir / "progress.json").write_text(
            json.dumps({"status": "queued"}, ensure_ascii=False), encoding="utf-8"
        )

        self._queue.put_nowait(job_id)
        self._prune_history()
        return job_id

    def _prune_history(self) -> None:
        """Keep only the newest MAX_HISTORY job dirs; delete older ones.

        Never removes the job that is currently running (its files are in use).
        """
        dirs = [d for d in self.jobs_root.iterdir() if d.is_dir()]
        # Sort newest-first by created_at (fall back to mtime if job.json missing).
        def _created(d: Path) -> str:
            job = _read_json(d / "job.json")
            if job and job.get("created_at"):
                return job["created_at"]
            return datetime.fromtimestamp(d.stat().st_mtime).isoformat()

        dirs.sort(key=_created, reverse=True)
        for stale in dirs[MAX_HISTORY:]:
            if stale.name == self._current:
                continue
            shutil.rmtree(stale, ignore_errors=True)

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
            "can_resume": False,
            "pages_done": progress.get("done", 0),
            "pages_total": progress.get("total", 0),
        }
        if error:
            out["message"] = error.get("message")
            out["suggest_retry_without_layout"] = error.get(
                "suggest_retry_without_layout", False
            )
            out["can_resume"] = error.get("can_resume", False)
            out["pages_done"] = error.get("pages_done", out["pages_done"])
            out["pages_total"] = error.get("pages_total", out["pages_total"])
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
        return jobs[:MAX_HISTORY]

    def get_job(self, job_id: str) -> dict | None:
        return _read_json(self._job_dir(job_id) / "job.json")

    # ----- deletion ---------------------------------------------------------
    def delete_job(self, job_id: str) -> str:
        """Delete a job's working directory. Returns 'deleted', 'running', or 'not_found'."""
        job_dir = self._job_dir(job_id)
        if not job_dir.exists():
            return "not_found"
        if self._current == job_id:
            return "running"
        shutil.rmtree(job_dir)
        return "deleted"

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
            self._attach_partial(job_id)  # salvage finished pages + allow resume
            return  # status already reflects the error

        # No error.json => the process died abnormally (segfault / OOM / kill).
        self._mark_crashed(
            job_id,
            f"Worker process crashed unexpectedly (exit code {returncode}). "
            "This usually means a native crash in the layout-aware OCR pipeline. "
            "Pages converted before the crash are saved — you can resume.",
        )

    def _mark_crashed(self, job_id: str, message: str) -> None:
        job_dir = self._job_dir(job_id)
        if not job_dir.exists():
            return

        # Salvage whatever pages finished before the crash so they aren't lost and
        # the job can resume from where it died (PDF jobs only).
        job = _read_json(job_dir / "job.json") or {}
        salvaged = self._salvage_partial(job_dir, job)
        done = salvaged["done"] if salvaged else 0
        total = salvaged["total"] if salvaged else 0
        can_resume = bool(job.get("file_type") == "pdf" and salvaged and done < total)

        (job_dir / "error.json").write_text(
            json.dumps(
                {
                    "message": message,
                    "suggest_retry_without_layout": True,
                    "can_resume": can_resume,
                    "pages_done": done,
                    "pages_total": total,
                    "updated_at": _now(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (job_dir / "progress.json").write_text(
            json.dumps(
                {
                    "status": "crashed",
                    "message": message,
                    "done": done,
                    "total": total,
                    "updated_at": _now(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _attach_partial(self, job_id: str) -> None:
        """Salvage finished pages for a worker-caught failure and mark it resumable.

        The hard-crash path (_mark_crashed) does its own salvage; this handles the
        other failure path, where the worker caught an exception and wrote
        error.json itself — we still want partial output + a Resume option.
        """
        job_dir = self._job_dir(job_id)
        job = _read_json(job_dir / "job.json") or {}
        salvaged = self._salvage_partial(job_dir, job)
        if not salvaged:
            return
        can_resume = bool(job.get("file_type") == "pdf" and salvaged["done"] < salvaged["total"])

        error = _read_json(job_dir / "error.json") or {}
        error.update(
            {
                "can_resume": can_resume,
                "pages_done": salvaged["done"],
                "pages_total": salvaged["total"],
            }
        )
        (job_dir / "error.json").write_text(json.dumps(error, ensure_ascii=False), encoding="utf-8")

        progress = _read_json(job_dir / "progress.json") or {"status": "error"}
        progress.update({"done": salvaged["done"], "total": salvaged["total"]})
        (job_dir / "progress.json").write_text(
            json.dumps(progress, ensure_ascii=False), encoding="utf-8"
        )

    def _selected_page_total(self, job_dir: Path, job: dict) -> int:
        """Number of pages in the job's selected range (for 'X of Y done')."""
        try:
            import fitz

            total = fitz.open(str(job_dir / "input.pdf")).page_count
        except Exception:  # noqa: BLE001 — best-effort count for the progress label
            return 0
        start = job.get("start_page", 0) or 0
        end = job.get("end_page")
        end = total if end is None else min(end, total)
        return max(0, end - start)

    def _salvage_partial(self, job_dir: Path, job: dict) -> dict | None:
        """Assemble converted.md + result.json from per-page files left on disk.

        Each page the worker finished persists as pages/<i>.md + pages/<i>.row.json
        (atomic writes), so even a hard segfault leaves those intact. Stitching
        them here means a crashed long run still yields a usable partial document
        and a populated stats/compare view — and a resume continues from here.
        Returns {"done", "total"} or None when nothing was salvageable.
        """
        if job.get("file_type") != "pdf":
            return None
        pages_dir = job_dir / "pages"
        if not pages_dir.exists():
            return None

        indices = []
        for md_file in pages_dir.glob("*.md"):
            try:
                indices.append(int(md_file.stem))
            except ValueError:
                continue
        if not indices:
            return None
        indices.sort()

        chunks, rows = [], []
        for i in indices:
            try:
                chunks.append((pages_dir / f"{i}.md").read_text(encoding="utf-8"))
            except OSError:
                continue
            row = _read_json(pages_dir / f"{i}.row.json") or {"page": i, "source": "ocr"}
            rows.append(row)

        total = self._selected_page_total(job_dir, job)
        (job_dir / "converted.md").write_text("\n\n".join(chunks), encoding="utf-8")
        (job_dir / "result.json").write_text(
            json.dumps(
                {"pages": rows, "label_col": "page", "page_count": total, "partial": True},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"done": len(rows), "total": total}

    # ----- resume -----------------------------------------------------------
    def resume_job(self, job_id: str) -> str:
        """Re-enqueue a crashed PDF job; the worker continues from saved pages.

        Returns 'resuming', 'running', 'not_resumable', or 'not_found'.
        """
        job_dir = self._job_dir(job_id)
        job = _read_json(job_dir / "job.json")
        if job is None:
            return "not_found"
        if self._current == job_id:
            return "running"
        if job.get("file_type") != "pdf":
            return "not_resumable"

        # Clear terminal markers so the worker re-runs; the partial converted.md /
        # result.json stay in place (served until the resumed run overwrites them).
        (job_dir / "error.json").unlink(missing_ok=True)
        (job_dir / "progress.json").write_text(
            json.dumps({"status": "queued"}, ensure_ascii=False), encoding="utf-8"
        )
        self._queue.put_nowait(job_id)
        return "resuming"
