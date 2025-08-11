from typing import List
from events import event
from core import wrapper

class DbInitialized(event.Event):
    def __init__(self, **kwargs):
        super().__init__('db_initialized', **kwargs)

class MessageSaved(event.Event):
    def __init__(self, **kwargs):
        super().__init__('message_saved', **kwargs)
        
class NewChatAck(event.Event):
    def __init__(self, chat: wrapper.ChatWrapper, **kwargs):
        super().__init__('new_chat_ack', chat=chat, **kwargs)

class MemoryRequest(event.Event):
    def __init__(self, chat_id: str, **kwargs):
        super().__init__('memory_request', chat_id=chat_id, **kwargs)

class MemoryResponse(event.Event):
    def __init__(self, chat_id: str, messages: List[wrapper.MessageWrapper], **kwargs):
        super().__init__('memory_response', chat_id=chat_id, messages=messages, **kwargs)