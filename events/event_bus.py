import asyncio
from contextlib import suppress
from typing import Type, TypeVar

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
        for handler in self._listeners.get(type(event), []):
            if asyncio.iscoroutinefunction(handler):
                asyncio.create_task(handler(event))
            else:
                handler(event)
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

    async def wait(self, requested_event: ev.Event, response_class: Type[ResponseType], timeout: float | None = 60.0) -> ResponseType:
        '''
        Emit *requested_event*, then block until a response of class *response_class*
        with the same event_id arrives, or until *timeout*.
        '''
        loop = asyncio.get_running_loop()
        future: asyncio.future[ResponseType] = loop.create_futureure()
        original = requested_event.event_id

        # one‑shot resolver
        def _resolver(response_event: ResponseType) -> None:
            # Use original_event_id if available, otherwise check event_id
            if (response_event.event_id == original) and not future.done():
                future.set_result(response_event)
                _remove_listener()

        # helper so resolver can remove itself
        def _remove_listener() -> None:
            with suppress(ValueError):
                self._listeners.get(response_class, []).remove(_resolver)
            if not self._listeners.get(response_class):
                self._listeners.pop(response_class, None)

        self.register(response_class, _resolver)
        await self.emit(requested_event)

        try:
            if timeout is None:
                return await future # no timeout
            return await asyncio.wait_for(future, timeout)
        finally:
            # ensure cleanup even on cancellation or TimeoutError
            if not future.done():
                future.cancel()
            _remove_listener()