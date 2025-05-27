from events import event

class ShutdownEvent(event.Event):
    def __init__(self, **kwargs):
        super().__init__('shutdown_event', **kwargs)

class ErrorEvent(event.Event):
    def __init__(self, error: str, e: Exception, **kwargs):
        super().__init__('error', error=error, e=e, **kwargs)