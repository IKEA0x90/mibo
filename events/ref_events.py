from typing import List

from events import event
from core import wrapper

class NewChat(event.Event):
    def __init__(self, chat: wrapper.ChatWrapper, **kwargs):
        super().__init__('new_chat', chat, **kwargs)

class NewMessage(event.Event):
    def __init__(self, chat_id: str, wrappers: List[wrapper.MessageWrapper], **kwargs):
        super().__init__('new_message', chat_id, wrappers, **kwargs)
