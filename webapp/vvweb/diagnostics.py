"""Local diagnostics for bug reports (docs/TECH_UPGRADE_PLAN.md, A6).

Desktop only: `/api/diagnostics` answers in local mode and is a 404 on a
shared demo, where recent errors could belong to other visitors. The report
holds versions, platform, limits, recent job states and recent warnings and
errors from the server log. It is shown to the person, who decides whether to
copy it; nothing is sent anywhere.
"""
from __future__ import annotations

import collections
import logging
import os
import platform
import re
import sys
import time
from typing import Any, Deque, Dict, List

from veriscript.logging_setup import ROOT_NAME

_PATH = re.compile(r"([A-Za-z]:)?([\\/][^\s\\/'\",:)]+){2,}")


class RecentLog(logging.Handler):
    """Keeps the last WARNING+ records in memory, file paths removed."""

    def __init__(self, capacity: int = 50) -> None:
        super().__init__(level=logging.WARNING)
        self.records: Deque[str] = collections.deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            when = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            text = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                text += f" [{type(exc).__name__}: {exc}]"
            text = _PATH.sub("<path>", " ".join(text.split()))[:300]
            self.records.append(f"{when} {record.levelname} {record.name}: {text}")
        except Exception:  # noqa: BLE001 - a log handler must never raise
            pass


recent_log = RecentLog()
logging.getLogger(ROOT_NAME).addHandler(recent_log)


def report(*, version: str, settings, jobs) -> Dict[str, Any]:
    recent_jobs: List[Dict[str, Any]] = []
    for job in list(jobs._jobs.values())[-10:]:
        recent_jobs.append({
            "status": job.status, "stage": job.stage,
            "page": job.page, "pages": job.pages,
            "seconds": round(((job.finished or time.time())
                              - (job.started or job.created)), 1),
            "error": job.error,
        })
    try:
        import onnxruntime as ort  # noqa: F401
        providers = ort.get_available_providers()
        ort_version = ort.__version__
    except Exception:  # noqa: BLE001
        providers, ort_version = [], None
    return {
        "app": f"VeriScript {version} ({settings.mode})",
        "python": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "cpus": os.cpu_count(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "onnxruntime": ort_version,
        "providers": providers,
        "limits": {
            "page_cap": settings.page_cap,
            "timeout_s": settings.process_timeout_s,
            "ttl_minutes": settings.run_ttl_minutes,
            "max_upload_mb": settings.max_upload_mb,
        },
        "jobs": recent_jobs,
        "log": list(recent_log.records),
    }


def as_text(data: Dict[str, Any]) -> str:
    lines = [data["app"],
             f"Python {data['python']} · {data['platform']} · {data['cpus']} CPUs"
             f"{' · installer build' if data['frozen'] else ''}",
             f"ONNX Runtime {data['onnxruntime'] or 'missing'}: "
             f"{', '.join(data['providers']) or 'no providers'}",
             "Limits: " + " · ".join(f"{k} {v}" for k, v in data["limits"].items()),
             "", "Recent jobs:"]
    lines += [f"  {j['status']} · {j['stage']} · page {j['page']}/{j['pages']} · "
              f"{j['seconds']} s" + (f" · {j['error']}" if j["error"] else "")
              for j in data["jobs"]] or ["  none"]
    lines += ["", "Recent warnings and errors:"]
    lines += [f"  {r}" for r in data["log"]] or ["  none"]
    return "\n".join(lines)
