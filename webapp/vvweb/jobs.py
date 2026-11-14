"""Background document jobs: a queue, one worker, progress and real cancel.

Why this exists (docs/TECH_UPGRADE_PLAN.md, Phase A1): the studio used to run
the whole pipeline inside the upload request. Waiting for the worker blocked
the event loop, and a timeout or Cancel only abandoned the request while the
pipeline thread kept running. The slot was then released early, so a second
OCR run could overlap the first (concurrent engine use has crashed the
process natively) and write into a deleted run folder.

Now an upload becomes a job. One worker thread takes jobs in order and holds
the shared worker semaphore for exactly as long as a job really runs. Cancel
and timeouts are cooperative: the pipeline checks between pages, and the job
only ends, and frees the slot, when its thread has actually stopped. The event
loop never blocks on any of this.
"""
from __future__ import annotations

import queue
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from veriscript.logging_setup import get_logger

_LOG = get_logger("web")  # same logger as the API: one place to read failures

QUEUED, RUNNING, DONE, FAILED, CANCELLED = (
    "queued", "running", "done", "failed", "cancelled")
FINISHED = {DONE, FAILED, CANCELLED}

#: Finished jobs stay queryable this long (results themselves live in the
#: run store; this is only the status record).
KEEP_FINISHED_S = 3600


class JobCancelled(Exception):
    """Raised inside the work function when the job should stop."""


class JobRejected(Exception):
    """The work function refused the input; the message is user-facing."""


@dataclass
class Job:
    id: str
    run_dir: str
    work: Callable[["Job"], Dict[str, Any]]
    timeout_s: float
    created: float = field(default_factory=time.time)
    status: str = QUEUED
    stage: str = "Waiting for the reader"
    page: int = 0
    pages: int = 0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_status: int = 500
    started: Optional[float] = None
    finished: Optional[float] = None
    cancel_requested: bool = False
    done: threading.Event = field(default_factory=threading.Event)

    # -- called from the work function -----------------------------------
    def progress(self, page: int, pages: int, stage: str) -> None:
        self.page, self.pages, self.stage = page, pages, stage

    def timed_out(self) -> bool:
        """`timeout_s <= 0` means no limit (the desktop app)."""
        return (self.timeout_s > 0 and self.started is not None
                and time.time() - self.started > self.timeout_s)

    def should_stop(self) -> bool:
        return self.cancel_requested or self.timed_out()

    def check(self) -> None:
        """Raise JobCancelled when the job should stop; call between steps."""
        if self.should_stop():
            raise JobCancelled()

    # -- reporting --------------------------------------------------------
    def public(self, position: Optional[int] = None) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "job_id": self.id,
            "status": self.status,
            "stage": self.stage,
            "page": self.page,
            "pages": self.pages,
            "cancel_requested": self.cancel_requested,
            "elapsed": round((self.finished or time.time())
                             - (self.started or self.created), 2),
        }
        if position is not None:
            out["position"] = position
        if self.status == DONE:
            out["result"] = self.result
        if self.status == FAILED:
            out["error"] = self.error
            out["error_status"] = self.error_status
        return out


class JobManager:
    """Runs jobs one at a time on a dedicated thread.

    `worker_sem` is the process-wide slot shared with the OCR warm-up and the
    video routes, so no two heavy operations ever overlap.
    """

    def __init__(self, worker_sem: threading.Semaphore,
                 busy: threading.Event, max_queued: int = 50) -> None:
        self._sem = worker_sem
        self._busy = busy
        self.max_queued = max_queued
        self._jobs: Dict[str, Job] = {}
        self._order: List[str] = []
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # -- submission -------------------------------------------------------
    def submit(self, job: Job) -> Job:
        with self._lock:
            if self.queued_count() >= self.max_queued:
                raise OverflowError("queue full")
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._ensure_thread()
        self._queue.put(job.id)
        return job

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="vv-jobs")
            self._thread.start()

    # -- queries ----------------------------------------------------------
    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def queued_count(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status == QUEUED)

    def position(self, job: Job) -> Optional[int]:
        """1 = next to run; None once it has started."""
        if job.status != QUEUED:
            return None
        waiting = [i for i in self._order
                   if self._jobs.get(i) and self._jobs[i].status == QUEUED]
        return waiting.index(job.id) + 1 if job.id in waiting else None

    def active(self) -> Optional[Job]:
        for job in self._jobs.values():
            if job.status == RUNNING:
                return job
        return None

    # -- cancel -----------------------------------------------------------
    def cancel(self, job_id: str) -> Optional[Job]:
        job = self._jobs.get(job_id)
        if job is None or job.status in FINISHED:
            return job
        with self._lock:
            job.cancel_requested = True
            never_started = job.status == QUEUED
            if never_started:
                # The worker re-checks the status under this lock, so it
                # skips the job instead of starting it.
                self._finish(job, CANCELLED, stage="Stopped")
            else:
                job.stage = "Stopping after the current page"
        if never_started:
            shutil.rmtree(job.run_dir, ignore_errors=True)
        return job

    # -- worker -----------------------------------------------------------
    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self._jobs.get(job_id)
            if job is None or job.status != QUEUED:
                continue
            with self._sem:
                with self._lock:
                    if job.status != QUEUED:  # cancelled while waiting
                        continue
                    job.status = RUNNING
                    job.started = time.time()
                    job.stage = "Starting"
                self._busy.set()
                try:
                    self._run(job)
                finally:
                    self._busy.clear()
            self._prune()

    def _run(self, job: Job) -> None:
        try:
            job.check()
            result = job.work(job)
            job.check()
        except JobCancelled:
            if job.cancel_requested:
                self._finish(job, CANCELLED, stage="Stopped")
            else:
                _LOG.warning("job %s timed out after %.0fs", job.id, job.timeout_s)
                self._finish(job, FAILED, stage="Timed out",
                             error="Processing took too long and was stopped.",
                             error_status=504)
            shutil.rmtree(job.run_dir, ignore_errors=True)
            return
        except JobRejected as exc:
            _LOG.warning("pipeline rejected the input (job=%s): %s", job.id, exc)
            self._finish(job, FAILED, stage="Failed", error=str(exc),
                         error_status=400)
            shutil.rmtree(job.run_dir, ignore_errors=True)
            return
        except Exception:  # noqa: BLE001 - reported to the client, logged here
            _LOG.exception("restore failed (run=%s)", job.id)
            self._finish(job, FAILED, stage="Failed",
                         error="The pipeline failed on this page. Try a cleaner "
                               "scan or a different file.",
                         error_status=500)
            shutil.rmtree(job.run_dir, ignore_errors=True)
            return
        job.result = result
        self._finish(job, DONE, stage="Done")

    def _finish(self, job: Job, status: str, *, stage: str,
                error: Optional[str] = None, error_status: int = 500) -> None:
        job.status = status
        job.stage = stage
        job.error = error
        job.error_status = error_status
        job.finished = time.time()
        job.done.set()

    def _prune(self) -> None:
        cutoff = time.time() - KEEP_FINISHED_S
        with self._lock:
            stale = [i for i, j in self._jobs.items()
                     if j.status in FINISHED and (j.finished or 0) < cutoff]
            for i in stale:
                self._jobs.pop(i, None)
            self._order = [i for i in self._order if i in self._jobs]
