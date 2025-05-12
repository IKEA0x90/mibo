import asyncio
from contextlib import suppress

from events import event as ev
    
class EventBus:
    def __init__(self):
        self.listeners = {}

    def register(self, event_class, handler):
        self._listeners.setdefault(event_class, []).append(handler)

    async def emit(self, event: ev.Event) -> ev.Event:
        for handler in self.listeners.get(event.name, []):
            if asyncio.iscoroutinefunction(handler):
                asyncio.create_task(handler(event))
            else:
                handler(event)
        return event

    async def wait(self, event: ev.Event, response_template: ev.Event, timeout: float = 60) -> ev.Event:
        '''
        Emit an event, then wait for and return the response event. 
        '''
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        # Once‑only resolver
        def _resolver(response_event: ev.Event):
            if response_event.event_id == event.event_id and not future.done():
                future.set_result(response_event)
                # unsubscribe itself
                self._listeners[response_event.name].remove(_resolver)

        self.register(response_template.name, _resolver)

        await self.emit(event)

        try:
            return await asyncio.wait_for(future, timeout) if timeout else await future
        finally:
            # Clean up if the waiter is cancelled or times out
            with suppress(ValueError):
                self._listeners.get(response_template.name, []).remove(_resolver)