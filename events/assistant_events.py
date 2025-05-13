from events import event
from core import wrapper

class AssistantResponse(event.Event):
    def __init__(self, response: wrapper.MessageWrapper, **kwargs):
        super().__init__('assistant_response', response=response, **kwargs)

class AssistantToolCall(event.Event):
    def __init__(self, tool_name: str, tool_args: dict, **kwargs):
        super().__init__('assistant_tool_call', tool_name=tool_name, tool_args=tool_args, **kwargs)

class AssistantToolResponse(event.Event):
    def __init__(self, response: wrapper.MessageWrapper, **kwargs):
        super().__init__('assistant_tool_response', response=response, **kwargs)