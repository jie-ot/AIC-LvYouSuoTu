"""Read-only, user-scoped progress for the existing synchronous generation."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps
import math
import threading
import time

from app.core.config import settings


@dataclass
class Progress:
    started: float = field(default_factory=time.monotonic)
    phase_started: float = field(default_factory=time.monotonic)
    phase: str = "preparing"
    finished: float | None = None
    photos: int = 0
    cards: int = 0
    report_requested: bool = False
    report_ready: bool = False
    report_started: float | None = None
    batches: dict[int, int] = field(default_factory=dict)
    ready_cards: set[int] = field(default_factory=set)
    card_steps: dict[int, tuple[str, float]] = field(default_factory=dict)


_active: ContextVar[Progress | None] = ContextVar("generation_progress", default=None)
_runs: dict[tuple[str, str], Progress] = {}
_lock = threading.RLock()
_LABELS = {"preparing": "正在准备照片", "locating": "正在整理照片时间与地点",
           "analyzing": "正在理解照片", "creating": "正在生成作品",
           "saving": "正在保存作品", "completed": "作品已保存", "failed": "本次生成未完成"}


@contextmanager
def track(user_id: str, request_id: str | None, *, photos: int, cards: int, report: bool):
    if not request_id:
        yield
        return
    progress = Progress(photos=photos, cards=cards, report_requested=report)
    with _lock:
        now = time.monotonic()
        for key in list(_runs):
            if now - _runs[key].started > 1800:
                del _runs[key]
        if len(_runs) >= 64:
            del _runs[min(_runs, key=lambda key: _runs[key].started)]
        _runs[(user_id, request_id)] = progress
    token = _active.set(progress)
    try:
        yield
    except Exception:
        set_phase("failed")
        raise
    else:
        set_phase("completed")
    finally:
        _active.reset(token)


def set_phase(phase: str) -> None:
    progress = _active.get()
    if progress is not None:
        with _lock:
            if progress.phase != phase:
                progress.phase = phase
                progress.phase_started = time.monotonic()
                if phase in {"completed", "failed"}:
                    progress.finished = progress.phase_started


def observe(event: str, status: str, fields: dict) -> None:
    """Consume existing validated log events; never expose model/tool payloads."""
    progress = _active.get()
    if progress is None:
        return
    if event == "generate_place_resolution" and status == "start":
        set_phase("locating")
    elif event == "generate_photo_analysis":
        if status == "start":
            set_phase("analyzing")
        elif status == "success":
            set_phase("creating")
    elif event == "orchestrator_photo_batch_validation" and status == "success":
        with _lock:
            progress.batches[int(fields["batch_index"])] = int(fields["returned_photo_count"])
    elif event == "orchestrator_report_copy_model" and status == "start":
        with _lock:
            progress.report_started = time.monotonic()


def card_step(index: int, step: str) -> None:
    progress = _active.get()
    if progress is not None:
        with _lock:
            progress.card_steps[index] = (step, time.monotonic())


def card_ready(index: int) -> None:
    progress = _active.get()
    if progress is not None:
        with _lock:
            progress.ready_cards.add(index)
            progress.card_steps[index] = ("done", time.monotonic())


def report_branch(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        result = function(*args, **kwargs)
        progress = _active.get()
        if progress is not None:
            with _lock:
                progress.report_ready = True
        return result
    return wrapped


def snapshot(user_id: str, request_id: str) -> dict | None:
    with _lock:
        progress = _runs.get((user_id, request_id))
        if progress is None or time.monotonic() - progress.started > 1800:
            return None
        now = progress.finished or time.monotonic()
        elapsed = int((now - progress.started) * 1000)
        phase_elapsed = int((now - progress.phase_started) * 1000)
        # Broad estimates informed by the 30-photo live run. Design, drawing,
        # report copy and the serialized reviews are separate pieces of work.
        analysis = math.ceil(math.ceil(progress.photos / 5) / max(1, settings.PHOTO_ANALYZE_PARALLELISM)) * 120_000
        artwork = _creation_remaining(progress, now)
        remaining = {"preparing": 20_000 + analysis + artwork, "locating": 20_000 + analysis + artwork,
                     "analyzing": analysis + artwork, "creating": artwork, "saving": 15_000}.get(progress.phase, 0)
        if progress.phase != "creating":
            remaining -= phase_elapsed
        done = progress.phase in {"completed", "failed"}
        details = []
        if progress.phase == "analyzing":
            details.append(f"照片 {min(progress.photos, sum(progress.batches.values()))}/{progress.photos}")
        elif progress.phase in {"creating", "saving", "completed"}:
            if progress.cards:
                details.append(f"明信片 {len(progress.ready_cards)}/{progress.cards}")
            if progress.report_requested:
                details.append("报告已整理" if progress.report_ready else "报告整理中")
        label = _creation_label(progress) if progress.phase == "creating" else _LABELS[progress.phase]
        return {"stage": progress.phase, "stageLabel": label, "detail": " · ".join(details),
                "elapsedMs": elapsed, "estimatedRemainingMs": max(0, remaining) if not done else None,
                "done": done, "failed": progress.phase == "failed"}


def _creation_label(progress: Progress) -> str:
    if not progress.cards or len(progress.ready_cards) == progress.cards:
        return "正在整理旅行报告" if progress.report_requested and not progress.report_ready else "正在整理作品"
    steps = [step for step, _ in progress.card_steps.values()]
    if not steps:
        return "正在设计明信片"
    if "repairing" in steps:
        return "正在调整明信片"
    if "drawing" in steps or len(steps) < progress.cards:
        return "正在绘制明信片"
    if "comparing" in steps:
        return "正在对照修改效果"
    return "正在检查明信片"


def _creation_remaining(progress: Progress, now: float) -> int:
    report = 0
    if progress.report_requested and not progress.report_ready:
        report = max(0, 120_000 - int((now - progress.report_started) * 1000)) if progress.report_started is not None else 120_000
    if not progress.cards:
        return report
    parallelism = max(1, settings.GENERATION_IMAGE_PARALLELISM)
    if not progress.card_steps:
        design_elapsed = int((now - progress.phase_started) * 1000) if progress.phase == "creating" else 0
        design = max(0, 150_000 - design_elapsed)
        drawing = math.ceil(progress.cards / parallelism) * 120_000
        return design + max(drawing, report) + progress.cards * 30_000
    drawing, reviewing = 0, 0
    queued = max(0, progress.cards - len(progress.card_steps))
    for step, started in progress.card_steps.values():
        elapsed = int((now - started) * 1000)
        if step in {"drawing", "repairing"}:
            drawing = max(drawing, max(0, 120_000 - elapsed))
        if step == "drawing":
            reviewing += 30_000
        elif step == "reviewing":
            reviewing += max(0, 30_000 - elapsed)
        elif step == "repairing":
            reviewing += 45_000  # Reserve the one comparison after image repair.
        elif step == "comparing":
            reviewing += max(0, 45_000 - elapsed)
    drawing += math.ceil(queued / parallelism) * 120_000
    reviewing += queued * 30_000
    # Report copy and artwork review share a model lock; drawing runs alongside.
    return max(drawing, report) + reviewing
