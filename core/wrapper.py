import tiktoken
import uuid
import re

import datetime as dt
from typing import List

from services import tools

class Wrapper():
    def __init__(self, id: str = None):
        self.content_id: str = str(id) if id is not None else str(uuid.uuid4())

    def tokens(self):
        encoding = tiktoken.encoding_for_model('gpt-4o')
        tokens = len(encoding.encode(str(self)))
        return tokens

class ImageWrapper(Wrapper):
    def __init__(self, x: int, y: int, image_url: str, image_base64: str = None):
        super().__init__()
        self.x = x or 0
        self.y = y or 0
        self.image_url: str = image_url or ''
        self.image_base64: str = ''
        self.image_description: str = ''

    async def tokens(self):
        width = (self.x + 512 -1) // 512 # round up by adding 511
        height = (self.y + 512 -1) // 512

        return 85 + 170 * (height + width)

class StickerWrapper(Wrapper):
    def __init__(self, key_emoji: str):
        super().__init__()
        self.key_emoji: str = key_emoji

    async def tokens(self):
        return 1

class PollWrapper(Wrapper):
    def __init__(self, question: str, options: List[str], multiple_choice: bool, correct_option_idx: int = 0, explanation: str = ''):
        super().__init__()
        self.question: str = question or ''
        self.options: List[str] = options or []
        self.multiple_choice: bool = multiple_choice or False
        self.correct_option_idx: int = correct_option_idx or -1
        self.explanation: str = explanation or ''

        if correct_option_idx != -1:
            self.multiple_choice = False

    def __str__(self):
        rstr = []
        rstr.append(f'Poll {"(multiple choice)" if self.multiple_choice else ""}: {self.question}\n')
        rstr.append('Options:\n')
        for i, option in enumerate(self.options):
            rstr.append(f"{i+1}. {option}")
        return rstr

class MessageWrapper(Wrapper):
    def __init__(self, chat_id: str, message_id: str = None, role: str = 'assistant', user: str = None, message: str = '', ping: bool = True, reply_id: str = '', datetime: dt.datetime = None, **kwargs):
        super().__init__(message_id)
        self.chat_id: str = str(chat_id)
        self.chat_name: str = kwargs.get('chat_name', '')
        self.role: str = role or 'assistant'
        self.user: str = user or tools.Tool.MIBO

        self.message: str = message or ''
        self.content_list: List[Wrapper] = []

        self.ping: bool = ping
        self.reply_id: str = str(reply_id or '') 

        try:
            self.datetime: dt.datetime = datetime.astimezone(dt.timezone.utc)
        except Exception:
            self.datetime = dt.datetime.now(tz=dt.timezone.utc)

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
    
    def get_sticker(self) -> StickerWrapper:
        stickers = [c for c in self.content_list if isinstance(c, StickerWrapper)]
        return stickers[0] if stickers else None
    
    def get_poll(self) -> PollWrapper:
        polls = [c for c in self.content_list if isinstance(c, PollWrapper)]
        return polls[0] if polls else None
    
    async def tokens(self, model='gpt-4o'):
        encoding = tiktoken.encoding_for_model(model)
            
        tokens = len(encoding.encode(str(self)))
        content_tokens = sum([c.tokens() for c in self.content_list])

        return tokens + content_tokens
    
class ChatWrapper():
    def __init__(self, chat_id: str, custom_instructions: str, chance: int, max_context_tokens: int, max_content_tokens: int, max_response_tokens: int, frequency_penalty: float, presence_penalty: float):
        self.chat_id: str = chat_id
        self.custom_instructions: str = custom_instructions or ''
        self.chance: int = chance or 5
        self.max_context_tokens: int = max_context_tokens or tools.Tool.MAX_CONTENT_TOKENS
        self.max_content_tokens: int = max_content_tokens or tools.Tool.MAX_CONTENT_TOKENS
        self.max_response_tokens: int = max_response_tokens or tools.Tool.MAX_RESPONSE_TOKENS
        self.frequency_penalty: float = frequency_penalty or tools.Tool.FREQUENCY_PENALTY
        self.presence_penalty: float = presence_penalty or tools.Tool.PRESENCE_PENALTY