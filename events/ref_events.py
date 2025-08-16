from typing import List

from events import event
from core import wrapper

class NewChat(event.Event):
    def __init__(self, chat: wrapper.ChatWrapper, **kwargs):
        super().__init__('new_chat', chat, **kwargs)