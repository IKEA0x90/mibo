from telegram import Update
from telegram.ext import CallbackContext
from typing import List
from datetime import datetime

from events import event
from core import wrapper

# Mibo events
class MiboMessage(event.Event):
    def __init__(self, update: Update, context: CallbackContext, start_datetime: datetime, **kwargs):
        super().__init__('mibo_message', update=update, context=context, start_datetime=start_datetime, **kwargs)

class MiboSystemMessage(event.Event):
    def __init__(self, update: Update, start_datetime: datetime, **kwargs):
        super().__init__('mibo_system_message', update=update, start_datetime=start_datetime, **kwargs)

class MiboCommand(event.Event):
    def __init__(self, update: Update, start_datetime: datetime, **kwargs):
            super().__init__('mibo_command', update=update, start_datetime=start_datetime, **kwargs)

class MiboMessageResponse(event.Event):
    def __init__(self, chat_id: str, text: str, images: List[wrapper.ImageWrapper], **kwargs):
        super().__init__('mibo_message_response', chat_id=chat_id, text=text, images=images, **kwargs)

class MiboStickerResponse(event.Event):
    def __init__(self, chat_id: str, sticker: wrapper.StickerWrapper, **kwargs):
        super().__init__('mibo_sticker_response', chat_id=chat_id, sticker=sticker, **kwargs)

class MiboPollResponse(event.Event):
    def __init__(self, chat_id: str, poll: wrapper.PollWrapper, **kwargs):
        super().__init__('mibo_poll_response', chat_id=chat_id, poll=poll, **kwargs)