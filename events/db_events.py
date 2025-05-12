from typing import List
from events import event

class DbInitialized(event.Event):
    def __init__(self, **kwargs):
        super().__init__('db_initialized', **kwargs)

class MessageSaved(event.Event):
    def __init__(self, **kwargs):
        super().__init__('message_saved', **kwargs)

class ImageSaveRequest(event.Event):
    def __init__(self, chat_id: str, file_bytes: List[bytes], **kwargs):
        super().__init__('image_save_request', chat_id=chat_id, file_bytes=file_bytes, **kwargs)

class ImageResponse(event.Event):
    def __init__(self, chat_id: str, image_paths: List[str], base64s: List[str], **kwargs):
        super().__init__('image_response', chat_id=chat_id, image_paths=image_paths, base64s=base64s, **kwargs)