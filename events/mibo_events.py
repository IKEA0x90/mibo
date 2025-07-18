from telegram import Update
from telegram.ext import CallbackContext
from typing import List
from datetime import datetime

from events import event
from core import wrapper

class MiboMessage(event.Event):
    def __init__(self, update: Update, context: CallbackContext, start_datetime: datetime, typing, **kwargs):
        super().__init__('mibo_message', update=update, context=context, start_datetime=start_datetime, typing=typing, **kwargs)

class MiboCommand(event.Event):
    def __init__(self, update: Update, start_datetime: datetime, **kwargs):
            super().__init__('mibo_command', update=update, start_datetime=start_datetime, **kwargs)

class MiboMessageResponse(event.Event):
    def __init__(self, chat_id: str, text: str, images: List[wrapper.ImageWrapper], **kwargs):
        super().__init__('mibo_message_response', chat_id=chat_id, text=text, images=images, **kwargs)

class MiboPollResponse(event.Event):
    def __init__(self, chat_id: str, poll: wrapper.PollWrapper, **kwargs):
        super().__init__('mibo_poll_response', chat_id=chat_id, poll=poll, **kwargs)

class AssistantCreated(event.Event):
    def __init__(self, chat_id: str, **kwargs):
        super().__init__('assistant_created', chat_id=chat_id, **kwargs)