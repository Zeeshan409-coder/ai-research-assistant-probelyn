"""Server-Sent Events helpers for streaming pipeline progress to the browser.

Each research pipeline runs as an independent background task that pushes its
events into a queue; the HTTP response only *reads* from that queue. If the
browser disconnects (user clicks "New research", closes the tab, …) the task
keeps running to completion, so the answer is still saved to the Library.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi.responses import StreamingResponse

from .llm import LLMError

log = logging.getLogger(__name__)

_DONE = object()
_running: set[asyncio.Task] = set()  # strong refs so tasks aren't garbage-collected
_by_entry: dict[str, asyncio.Task] = {}  # entry id -> task, so the Stop button can cancel it


def format_event(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _pump(events: AsyncIterator[dict], queue: asyncio.Queue) -> None:
    entry_id = None
    try:
        async for ev in events:
            if ev["event"] == "entry":
                entry_id = ev["data"]["entry_id"]
                _by_entry[entry_id] = asyncio.current_task()
            queue.put_nowait(ev)
    except asyncio.CancelledError:
        queue.put_nowait({"event": "stopped", "data": {"entry_id": entry_id}})
        # swallow: the task ends normally after recording the partial answer
    except LLMError as e:
        queue.put_nowait({"event": "error", "data": {"message": str(e)}})
    except Exception as e:  # never leave the client hanging
        log.exception("pipeline failed")
        queue.put_nowait({"event": "error", "data": {"message": f"Unexpected error: {e}"}})
    finally:
        if entry_id:
            _by_entry.pop(entry_id, None)
        queue.put_nowait(_DONE)


def stop_run(entry_id: str) -> bool:
    """Cancel a running pipeline. Cancelling closes the HTTP stream to Ollama, which halts generation."""
    task = _by_entry.get(entry_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def run_detached(events: AsyncIterator[dict]) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(_pump(events, queue))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return queue


async def _drain(queue: asyncio.Queue) -> AsyncIterator[str]:
    while True:
        ev = await queue.get()
        if ev is _DONE:
            return
        yield format_event(ev["event"], ev["data"])


def sse_response(events: AsyncIterator[dict]) -> StreamingResponse:
    return StreamingResponse(
        _drain(run_detached(events)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
