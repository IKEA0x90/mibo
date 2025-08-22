from telegram import Update
from telegram.ext import CallbackContext

from events import event

class NewMessageArrived(event.Event):
    def __init__(self, update: Update, context: CallbackContext, typing = None, **kwargs):
        super().__init__('new_message_arrived', update=update, context=context, typing=typing, **kwargs)