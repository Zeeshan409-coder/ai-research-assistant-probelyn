"""Wraps a pipeline's event stream so every run is saved to the history."""

import asyncio
from collections.abc import AsyncIterator

from ..db import EntryRecorder

STORE_SOURCES = "_store_sources"  # internal event: sources to persist, not sent to the browser


async def recorded(kind: str, question: str, model: str | None, events: AsyncIterator[dict]) -> AsyncIterator[dict]:
    rec = EntryRecorder(kind, question, model)
    yield {"event": "entry", "data": {"entry_id": rec.id}}
    try:
        async for ev in events:
            name = ev["event"]
            if name == STORE_SOURCES:
                rec.sources(ev["data"])
                continue
            if name == "token":
                rec.token(ev["data"])
            elif name == "error":
                rec.fail(ev["data"]["message"])
                yield ev
                return
            yield ev
    except asyncio.CancelledError:  # user pressed Stop: keep what was written so far
        rec.stop()
        raise
    except Exception as e:
        rec.fail(str(e))
        raise
    yield {"event": "done", "data": {"entry_id": rec.finish()}}
