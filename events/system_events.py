from typing import Tuple
from events import event

class ShutdownEvent(event.Event):
    def __init__(self, **kwargs):
        super().__init__('shutdown_event', **kwargs)

class ErrorEvent(event.Event):
    def __init__(self, error: str, e: Exception, tb: Tuple = None, **kwargs):
        super().__init__('error', error=error, e=e, tb=tb, **kwargs)