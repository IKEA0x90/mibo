import tiktoken
import uuid
import re

import datetime as dt
from typing import List

from services import tools

class Wrapper():
    def __init__(self, id: str = None):
        self.id: str = str(id) if id is not None else str(uuid.uuid4())

    def to_dict(self):
        return {
            'id': self.id,
        }

class ImageWrapper(Wrapper):
    def __init__(self, x: int, y: int, image_bytes: bytes, **kwargs):
        super().__init__()
        self.x = x or 0
        self.y = y or 0
        self.image_bytes: bytes = image_bytes or b''

        self.image_summary: str = kwargs.get('image_summary', '')

    def content_tokens(self):
        width = (self.x + 512 -1) // 512 # round up by adding 511
        height = (self.y + 512 -1) // 512

        return 85 + 170 * (height + width)
    
    def to_dict(self):
        return {
            'image_id': self.id,
            'x': self.x,
            'y': self.y,
            'image_bytes': self.image_bytes,
            'image_summary': self.image_summary,
            'content_tokens': self.content_tokens(),
        }

class MessageWrapper(Wrapper):
    def __init__(self, chat_id: str, message_id: str = None, role: str = 'assistant', user: str = None, message: str = '', ping: bool = True, reply_id: str = '', datetime: dt.datetime = None, **kwargs):
        super().__init__(message_id)
        self.chat_id: str = str(chat_id)
        self.chat_name: str = kwargs.get('chat_name', '')
        self.role: str = role or 'assistant'
        self.user: str = user or tools.Tool.MIBO

        self.reactions: List[str] = kwargs.get('reactions', [])

        self.message: str = message or ''
        self.content_list: List[Wrapper] = []

        self.ping: bool = ping
        self.reply_id: str = str(reply_id or '') 

        try:
            self.datetime: dt.datetime = datetime.astimezone(dt.timezone.utc)
        except Exception:
            self.datetime = dt.datetime.now(tz=dt.timezone.utc)

    def to_dict(self):
        return {
            'message_id': self.id,
            'chat_id': self.chat_id,
            'role': self.role,
            'user': self.user,
            'reactions': self.reactions,
            'message': self.message,
            'context_tokens': self.context_tokens(),
            'content_tokens': self.content_tokens(),
            'reply_id': self.reply_id,
            'datetime': self.datetime,
        }

    def __str__(self):
        return f'{self.user}: {self._remove_prefix(self.message)}'

    @staticmethod
    def _remove_prefix(text: str) -> str:
        '''
        Removes the prefixed name from the text if it exists
        '''
        prefix = tools.Tool.MIBO_MESSAGE  # 'mibo:'
        pattern = rf'^(?:{prefix.rstrip()}\s+)+'
        text2 = text.strip()

        if re.match(pattern, text, flags=re.IGNORECASE):
            text2 = re.sub(pattern, '', text, flags=re.IGNORECASE)

        return text2

    def add_content(self, content: Wrapper):
        self.content_list.append(content)

    def get_images(self) -> List[ImageWrapper]:
        return [c for c in self.content_list if isinstance(c, ImageWrapper)]
    
    def context_tokens(self, model='gpt-4o'):
        encoding = tiktoken.encoding_for_model(model)
        tokens = len(encoding.encode(str(self)))
        return tokens
    
    def content_tokens(self, model='gpt-4o'):
        # this works in py 3.12+ but runs sequentially.
        # c.content_tokens() runs fast enough for that not to be a problem.
        content_tokens = sum([c.content_tokens() for c in self.content_list])

        return content_tokens
    
class ChatWrapper(Wrapper):
    def __init__(self, chat_id: str, chat_name: str, custom_instructions: str, chance: int, max_context_tokens: int, max_content_tokens: int, max_response_tokens: int, frequency_penalty: float, presence_penalty: float):
        super().__init__(chat_id)
        self.chat_name: str = chat_name
        self.custom_instructions: str = custom_instructions or ''
        self.chance: int = chance or 5
        self.max_context_tokens: int = max_context_tokens or tools.Tool.MAX_CONTENT_TOKENS
        self.max_content_tokens: int = max_content_tokens or tools.Tool.MAX_CONTENT_TOKENS
        self.max_response_tokens: int = max_response_tokens or tools.Tool.MAX_RESPONSE_TOKENS
        self.frequency_penalty: float = frequency_penalty or tools.Tool.FREQUENCY_PENALTY
        self.presence_penalty: float = presence_penalty or tools.Tool.PRESENCE_PENALTY

    def to_dict(self):
        return {
            'chat_id': self.chat_id,
            'chat_name': self.chat_name,
            'custom_instructions': self.custom_instructions,
            'chance': self.chance,
            'max_context_tokens': self.max_context_tokens,
            'max_content_tokens': self.max_content_tokens,
            'max_response_tokens': self.max_response_tokens,
            'frequency_penalty': self.frequency_penalty,
            'presence_penalty': self.presence_penalty,
        }