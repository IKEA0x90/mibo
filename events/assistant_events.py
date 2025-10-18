from typing import List
from events import event
from core import wrapper

class CompletionResponse(event.Event):
    def __init__(self, chat_id: str, wrapper_list: List[wrapper.Wrapper], typing, **kwargs):
        super().__init__('completion_response', wrapper_list=wrapper_list, typing=typing, **kwargs)

class AssistantResponse(event.Event):
    def __init__(self, messages: List[wrapper.Wrapper], typing, **kwargs):
        super().__init__('assistant_response', messages=messages, typing=typing, **kwargs)