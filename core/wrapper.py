import tiktoken
import uuid
from typing import List

class Wrapper():
    def __init__(self, id: str = None):
        self.content_id: str = id or str(uuid.uuid4())

class ImageWrapper(Wrapper):
    def __init__(self, image_url: str):
        super().__init__()
        self.image_url: List[str] = image_url or ''
        self.image_description: str = ''

class StickerWrapper(Wrapper):
    def __init__(self, key_emoji: str, sticker_pack: str):
        super().__init__()
        self.key_emoji: str = key_emoji

class PollWrapper(Wrapper):
    def __init__(self, question: str, options: List[str], multiple_choice: bool):
        super().__init__()
        self.question: str = question or ''
        self.options: List[str] = options or []
        self.multiple_choice: bool = multiple_choice or False

class MessageWrapper(Wrapper):
    def __init__(self, chat_id: str, message_id: str, role: str, user: str, message: str, ping: bool = True, reply_id: str = ''):
        super().__init__(message_id)
        self.chat_id: str = chat_id
        self.role: str = role or 'assistant'
        self.user: str = user or 'itsmiibot'

        self.message: str = message or ''
        self.content_list: List[Wrapper] = []

        self.ping: bool = ping
        self.reply_id: str = reply_id or ''
        
        self.tokens = len(tiktoken.encoding_for_model("gpt-4o").encode(message))

    def add_content(self, content: Wrapper):
        self.content_list.append(content)