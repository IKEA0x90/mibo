from telegram import Update
from datetime import datetime

from events import event

# Mibo events
class MiboMessage(event.Event):
    def __init__(self, update: Update, start_datetime: datetime, **kwargs):
        super().__init__('mibo_message', update=update, start_datetime=start_datetime, **kwargs)

class MiboSystemMessage(event.Event):
    def __init__(self, update: Update, start_datetime: datetime, **kwargs):
        super().__init__('mibo_message', update=update, start_datetime=start_datetime, **kwargs)

class MiboCommand(event.Event):
    def __init__(self, update: Update, start_datetime: datetime, **kwargs):
            super().__init__('mibo_command', update=update, start_datetime=start_datetime, **kwargs)