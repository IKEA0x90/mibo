from typing import List
from telegram import Update
from telegram.ext import CallbackContext

from events import event

class NewMessageArrived(event.Event):
    def __init__(self, update: Update, context: CallbackContext, typing, **kwargs):
        super().__init__('new_message_arrived', update=update, context=context, typing=typing, **kwargs)

class TelegramIDUpdateRequest(event.Event):
    def __init__(self, messages: List, **kwargs):
        super().__init__('telegram_id_update_request', messages=messages, **kwargs)