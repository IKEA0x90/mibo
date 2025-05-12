from telegram import Update

from events import event

# Mibo events
class MiboMessage(event.Event):
    def __init__(self, update: Update, **kwargs):
        super().__init__('mibo_message', update=update, **kwargs)

class MiboSystemMessage(event.Event):
    def __init__(self, update: Update, **kwargs):
        super().__init__('mibo_message', update=update, **kwargs)

class MiboCommand(event.Event):
    def __init__(self, update: Update, **kwargs):
            super().__init__('mibo_command', update=update, **kwargs)