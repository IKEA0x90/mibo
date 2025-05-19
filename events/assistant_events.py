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

class AssistantReadyResponse(event.Event):
    def __init__(self, **kwargs):
        super().__init__('assistant_ready_response', **kwargs)

class AssistantDirectRequest(event.Event):
    def __init__(self, message: wrapper.MessageWrapper, **kwargs):
        super().__init__('assistant_direct_request', message=message, **kwargs)