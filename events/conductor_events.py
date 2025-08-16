from events import event
from core import window

class CompletionRequest(event.Event):
    def __init__(self, wdw: window.Window, **kwargs):
        super().__init__('completion_request', wdw, **kwargs)
