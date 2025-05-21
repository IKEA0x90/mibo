from telegram import Message
from typing import List

from events import event
from core import wrapper

class MessagePush(event.Event):
    def __init__(self, message: wrapper.MessageWrapper, **kwargs):
        super().__init__('message_request', request=message, **kwargs)

class AssistantRequest(event.Event):
    def __init__(self, chat_id: str, message: wrapper.MessageWrapper, **kwargs):
        super().__init__('assistant_call', chat_id=chat_id, message=message, **kwargs)

class ImageDownloadRequest(event.Event):
    def __init__(self, update, context, **kwargs):
        super().__init__('image_download_request', update=update, context=context, **kwargs)

class NewChatPush(event.Event):
    def __init__(self, chat: wrapper.ChatWrapper, **kwargs):
        super().__init__('new_chat_created', chat=chat, **kwargs)