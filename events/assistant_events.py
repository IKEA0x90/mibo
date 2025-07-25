from typing import List
from events import event
from core import wrapper

class AssistantResponse(event.Event):
    def __init__(self, messages: List[wrapper.Wrapper], **kwargs):
        super().__init__('assistant_response', messages=messages, **kwargs)

class AssistantToolRequest(event.Event):
    def __init__(self, chat_id: str, tool_name: str, tool_args: str, **kwargs):
        super().__init__('assistant_tool_request', chat_id=chat_id, tool_name=tool_name, tool_args=tool_args, **kwargs)

class AssistantToolResponse(event.Event):
    def __init__(self, response: wrapper.Wrapper, **kwargs):
        super().__init__('assistant_tool_response', response=response, **kwargs)

class AssistantToolPush(event.Event):
    def __init__(self, response: wrapper.Wrapper, **kwargs):
        super().__init__('assistant_tool_push', response=response, **kwargs)

class AssistantDirectRequest(event.Event):
    def __init__(self, message: wrapper.Wrapper, **kwargs):
        super().__init__('assistant_direct_request', message=message, **kwargs)

class AssistantSystemReply(event.Event):
    def __init__(self, message: wrapper.Wrapper, **kwargs):
        super().__init__('assistant_system_reply', message=message, **kwargs)