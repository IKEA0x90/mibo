from typing import List
from events import event
from core import wrapper

class DbInitialized(event.Event):
    def __init__(self, **kwargs):
        super().__init__('db_initialized', **kwargs)

class MessageSaved(event.Event):
    def __init__(self, **kwargs):
        super().__init__('message_saved', **kwargs)
        
class NewChatPush(event.Event):
    def __init__(self, chat, **kwargs):
        super().__init__('new_chat_created', chat=chat, **kwargs)

class NewChatAck(event.Event):
    def __init__(self, chat: wrapper.ChatWrapper, **kwargs):
        super().__init__('new_chat_ack', chat=chat, **kwargs)

class ImageSaveRequest(event.Event):
    def __init__(self, chat_id: str, file_bytes: List[bytes], **kwargs):
        super().__init__('image_save_request', chat_id=chat_id, file_bytes=file_bytes, **kwargs)

class ImageResponse(event.Event):
    def __init__(self, chat_id: str, images: List[wrapper.ImageWrapper], **kwargs):
        super().__init__('image_response', chat_id=chat_id, images=images or [], **kwargs)

class MemoryRequest(event.Event):
    def __init__(self, chat_id: str, **kwargs):
        super().__init__('memory_request', chat_id=chat_id, **kwargs)

class MemoryResponse(event.Event):
    def __init__(self, chat_id: str, messages: List[wrapper.MessageWrapper], **kwargs):
        super().__init__('memory_response', chat_id=chat_id, messages=messages, **kwargs)