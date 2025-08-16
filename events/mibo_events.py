from telegram import Update
from telegram.ext import CallbackContext
from typing import List

from events import event
from core import wrapper

class NewMessageArrived(event.Event):
    def __init__(self, update: Update, context: CallbackContext, typing, **kwargs):
        super().__init__('new_message_arrived', update=update, context=context, typing=typing, **kwargs)

class MiboMessageResponse(event.Event):
    def __init__(self, chat_id: str, text: str, images: List[wrapper.ImageWrapper], **kwargs):
        super().__init__('mibo_message_response', chat_id=chat_id, text=text, images=images, **kwargs)

class MiboPollResponse(event.Event):
    def __init__(self, chat_id: str, poll: wrapper.PollWrapper, **kwargs):
        super().__init__('mibo_poll_response', chat_id=chat_id, poll=poll, **kwargs)

class AssistantCreated(event.Event):
    def __init__(self, chat_id: str, **kwargs):
        super().__init__('assistant_created', chat_id=chat_id, **kwargs)