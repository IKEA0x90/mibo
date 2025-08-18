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
        handlers_to_await = []
        for handler in self._listeners.get(type(event), []):
            if asyncio.iscoroutinefunction(handler):
                handlers_to_await.append(handler(event))
            else:
                handler(event)
        
        if handlers_to_await:
            await asyncio.gather(*handlers_to_await)
            
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

    async def wait(self, requested_event: ev.Event, response_class: Type[ResponseType], timeout: float | None = 360.0) -> ResponseType:
        '''
        Emit *requested_event*, then block until a response of class *response_class*
        with the same event_id arrives, or until *timeout*.
        '''
        loop = asyncio.get_running_loop()
        future: asyncio.future[ResponseType] = loop.create_future()
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

    async def wait_for_all(self, requested_event: "ev.Event", response_classes: List[Type[ResponseType]], timeout: float | None = 360.0) -> List[ResponseType]:
        '''
        Same as wait, but waits for all response classes in *response_classes*.
        '''
        if not response_classes:
            raise ValueError('response_classes must contain at least one class to wait for.')

        loop = asyncio.get_running_loop()
        all_done: asyncio.Future[List[ResponseType]] = loop.create_future()
        original = requested_event.event_id

        results: List = [None] * len(response_classes)
        remaining = set(range(len(response_classes)))

        resolvers: List = [None] * len(response_classes)

        def _make_remove_listener(idx: int, cls: Type[ResponseType]):
            def _remove_listener() -> None:
                with suppress(ValueError):
                    self._listeners.get(cls, []).remove(resolvers[idx])
                if not self._listeners.get(cls):
                    self._listeners.pop(cls, None)
            return _remove_listener

        remove_funcs = [None] * len(response_classes)

        for i, cls in enumerate(response_classes):
            remove_funcs[i] = _make_remove_listener(i, cls)

            def _resolver(response_event: ResponseType, *, _i=i, _cls=cls) -> None:
                if response_event.event_id != original:
                    return

                if results[_i] is not None:
                    return

                results[_i] = response_event
                remove_funcs[_i]()

                remaining.discard(_i)
                if not remaining and not all_done.done():
                    all_done.set_result(list(results))
            resolvers[i] = _resolver
            self.register(cls, _resolver)

        await self.emit(requested_event)

        try:
            if timeout is None:
                return await all_done
            return await asyncio.wait_for(all_done, timeout)
        finally:
            if not all_done.done():
                all_done.cancel()
            for i, cls in enumerate(response_classes):
                if resolvers[i] is not None:
                    with suppress(Exception):
                        remove_funcs[i]()