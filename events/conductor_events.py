from telegram import Message
from typing import List

from events import event
from core import wrapper

class MessagePush(event.Event):
    def __init__(self, message: wrapper.MessageWrapper, **kwargs):
        super().__init__('message_request', request=message, **kwargs)

class AssistantRequest(event.Event):
    def __init__(self, request: List[wrapper.MessageWrapper], **kwargs):
        super().__init__('assistant_call', request=request, **kwargs)

class ImageDownloadRequest(event.Event):
    def __init__(self, message: Message, **kwargs):
        super().__init__('image_download_request', message=message, **kwargs)