from events import event

class ShutdownRequested(event.Event):
    def __init__(self, **kwargs):
        super().__init__('shutdown_requested', **kwargs)

class ChatErrorEvent(event.Event):
    def __init__(self, chat_id: str, error: str, traceback: Exception, **kwargs):
        super().__init__('error', chat_id=chat_id, error=error, e=traceback, **kwargs)

class ErrorEvent(event.Event):
    def __init__(self, error: str, traceback: Exception, **kwargs):
        super().__init__('error', error=error, e=traceback, **kwargs)