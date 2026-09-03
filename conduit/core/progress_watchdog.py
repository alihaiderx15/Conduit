
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class ProgressStalledError(RuntimeError):
    pass


@dataclass(slots=True)
class ProgressSnapshot:
    elapsed_seconds: float
    seconds_since_progress: float
    heartbeat_count: int
    progress_units: int
    detail: str
    missed_checks: int


async def run_with_progress_watchdog(
    operation_factory: Callable[[Callable[[int, str], None]], Awaitable[T]],
    *,
    check_interval: float = 60.0,
    initial_missed_checks: int = 2,
    active_missed_checks: int = 1,
    on_check: Callable[[ProgressSnapshot], object] | None = None,
) -> T:
    """No overall deadline; cancel only when observable progress stalls."""
    interval = max(0.01, float(check_interval))
    started = time.monotonic()
    last_progress = started
    heartbeat_count = 0
    progress_units = 0
    detail = "request started"
    progress_seen = False
    last_checked_heartbeat = 0
    missed = 0

    def heartbeat(units: int = 1, message: str = "") -> None:
        nonlocal last_progress, heartbeat_count, progress_units, detail, progress_seen
        heartbeat_count += 1
        progress_units += max(0, int(units))
        if message:
            detail = str(message)
        last_progress = time.monotonic()
        progress_seen = True

    task = asyncio.create_task(operation_factory(heartbeat))
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=interval)
            if task in done:
                return await task

            now = time.monotonic()
            if heartbeat_count > last_checked_heartbeat:
                missed = 0
            else:
                missed += 1
            last_checked_heartbeat = heartbeat_count

            snapshot = ProgressSnapshot(
                elapsed_seconds=now - started,
                seconds_since_progress=now - last_progress,
                heartbeat_count=heartbeat_count,
                progress_units=progress_units,
                detail=detail,
                missed_checks=missed,
            )
            if on_check is not None:
                value = on_check(snapshot)
                if inspect.isawaitable(value):
                    await value

            allowed = active_missed_checks if progress_seen else initial_missed_checks
            if missed >= max(1, int(allowed)):
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
                phase = "after output had started" if progress_seen else "before any output arrived"
                raise ProgressStalledError(
                    f"The AI coding task stopped making progress {phase}. "
                    f"No new progress was detected for about {int(snapshot.seconds_since_progress)} seconds."
                )
    finally:
        if not task.done():
            task.cancel()
