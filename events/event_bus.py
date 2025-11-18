import asyncio
from contextlib import suppress
from typing import List, Type, TypeVar

from events import event as ev

ResponseType = TypeVar('ResponseType', bound=ev.Event)
    
class EventBus:
    def __init__(self):
        self._listeners: dict[type[ev.Event], list] = {}
        self._tasks: set[asyncio.Task] = set() # track auto‑spawned tasks

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
    
    async def close(self): 
        # Cancel whatever is still running.
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def register(self, event_cls: type[ev.Event], handler) -> None:
        self._listeners.setdefault(event_cls, []).append(handler)

    def unregister(self, event_cls: type[ev.Event], handler) -> None:
        if event_cls in self._listeners:
            try:
                self._listeners[event_cls].remove(handler)
            except ValueError:
                pass
            if not self._listeners[event_cls]:
                del self._listeners[event_cls]

    async def emit(self, event: ev.Event) -> ev.Event:
        """
        Fire-and-forget emit.
        Any coroutine handlers are scheduled as tasks and NOT awaited here.
        Synchronous handlers run inline.
        Callers may still `await bus.emit(...)` for API compatibility; the await
        will resolve immediately after scheduling tasks.
        """
        for handler in self._listeners.get(type(event), []):
            if asyncio.iscoroutinefunction(handler):
                # schedule and track task
                self._spawn(handler(event))
            else:
                try:
                    handler(event)
                except Exception:
                    # swallow exceptions in sync handlers to avoid breaking emitter
                    # (consider emitting an ErrorEvent here if desired)
                    pass
        return event
    
    def emit_sync(self, event: ev.Event) -> None:
        '''
        Synchronous version of emit that can be called from synchronous contexts.
        It schedules the async emit to run in the event loop.
        '''
        try:
            loop = asyncio.get_running_loop()
            self._spawn(self.emit(event))
        except RuntimeError:
            # No running event loop
            asyncio.run_coroutine_threadsafe(self.emit(event), asyncio.get_event_loop())