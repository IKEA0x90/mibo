from typing import List
from events import event
from core import wrapper

class AssistantResponse(event.Event):
    def __init__(self, messages: List[wrapper.Wrapper], **kwargs):
        super().__init__('assistant_response', messages=messages, **kwargs)