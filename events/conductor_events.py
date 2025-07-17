from telegram import Message
from typing import List

from events import event
from core import wrapper

class WrapperPush(event.Event):
    def __init__(self, wrapper_list: List[wrapper.Wrapper], chat_id: str, **kwargs):
        super().__init__('wrapper_push', wrapper_list=wrapper_list, chat_id=chat_id, **kwargs)

class AssistantRequest(event.Event):
    def __init__(self, chat_id: str, messages: List[wrapper.Wrapper], **kwargs):
        super().__init__('assistant_call', chat_id=chat_id, messages=messages, **kwargs)

class NewChatPush(event.Event):
    def __init__(self, chat: wrapper.ChatWrapper, **kwargs):
        super().__init__('new_chat_created', chat=chat, **kwargs)