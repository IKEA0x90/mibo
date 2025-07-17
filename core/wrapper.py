import base64
import tiktoken
import re

import datetime as dt
from typing import Any, Dict, List, Literal, Optional

from services import tools

wrapper_types = Literal['message', 'image', 'poll']

class Wrapper():
    def __init__(self, id: str, chat_id: str, type: wrapper_types, datetime: dt.datetime = None):
        self.id: str = str(id)
        self.chat_id: str = str(chat_id)
        self.type: wrapper_types = str(type)

        self.tokens: int = 0

        try:
            self.datetime: dt.datetime = datetime.astimezone(dt.timezone.utc)
        except Exception:
            self.datetime = dt.datetime.now(tz=dt.timezone.utc)

    def to_parent_dict(self) -> Dict[str, Any]:
        '''
        Common meta row for the parent wrappers table
        '''
        return {
            'telegram_id': self.id,
            'chat_id': self.chat_id,
            'wrapper_type': self.type,
            'datetime': self.datetime,
            'tokens': self.tokens,
        }

    def to_child_dict(self) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses should implement this method to return child-specific data.")

    def calculate_tokens(self):
        raise NotImplementedError("Subclasses should implement this method to calculate tokens.")

class MessageWrapper(Wrapper):
    def __init__(self, message_id: str, chat_id: str, role: str = 'assistant', user: str = None, message: str = '', ping: bool = True, reply_id: str = '', **kwargs):
        super().__init__(message_id, chat_id, type='message', datetime=kwargs.get('datetime', None))
        
        self.chat_name: str = kwargs.get('chat_name', '')
        self.role: str = role or 'assistant'
        self.user: str = user or tools.Tool.MIBO

        self.reactions: List[str] = kwargs.get('reactions', [])

        self.message: str = message or ''

        self.ping: bool = ping
        self.reply_id: str = str(reply_id or '') 

    def to_child_dict(self):
        return {
            'role': self.role,
            'user': self.user,
            'message': self.message,
            'reply_id': self.reply_id,
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
    
    def calculate_tokens(self, model='gpt-4o'):
        encoding = tiktoken.encoding_for_model(model)
        tokens = len(encoding.encode(str(self)))
        return tokens

class ImageWrapper(Wrapper):
    def __init__(self, image_id: str, chat_id: str, x: int, y: int, image_bytes: Optional[bytes] = None, image_path: Optional[str] = None, **kwargs):
        super().__init__(image_id, chat_id, type='image', datetime=kwargs.get('datetime', None))
        self.x = x or 0
        self.y = y or 0

        self.image_bytes: bytes = image_bytes or b''
        self.image_path: str = image_path or ''

        self.image_summary: str = kwargs.get('image_summary', '')
        
        self.tokens_precalculated: int = kwargs.get('tokens', False)
        self.summary_tokens: int = kwargs.get('summary_tokens', 0)

    def calculate_tokens(self):
        if self.image_bytes is not None and self.tokens_precalculated:
            return self.tokens_precalculated
        
        elif self.image_bytes is None and self.summary_tokens:
            return self.summary_tokens
        
        else:
            width = (self.x + 512 -1) // 512 # round up by adding 511
            height = (self.y + 512 -1) // 512

            return 85 + 170 * (height + width)
    
    def get_base64(self) -> str:
        '''
        Get the base64 of the image bytes.
        '''
        if not self.image_bytes:
            return ''
        return base64.b64encode(self.image_bytes).decode('utf-8')

    def to_child_dict(self):
        return {
            'x': self.x,
            'y': self.y,
            'image_path': self.image_path,
            'image_summary': self.image_summary,
        }
    
class PollWrapper(Wrapper):
    def __init__(self, poll_id: str, chat_id: str, question: str, options: List[str], multiple_choice: bool, correct_option_idx: int = 0, explanation: str = '', **kwargs):
        super().__init__(poll_id, chat_id, type='poll', datetime=kwargs.get('datetime', None))

        self.question: str = question or ''
        self.options: List[str] = options or []
        self.multiple_choice: bool = multiple_choice or False
        self.correct_option_idx: int = correct_option_idx or -1
        self.explanation: str = explanation or ''

        if correct_option_idx != -1:
            self.multiple_choice = False

    def calculate_tokens(self, model='gpt-4o'):
        encoding = tiktoken.encoding_for_model(model)
        tokens = len(encoding.encode(str(self)))
        return tokens
    
    def to_child_dict(self):
        return {
            'question': self.question,
            'options': self.options,
            'multiple_choice': self.multiple_choice,
            'correct_option_idx': self.correct_option_idx,
            'explanation': self.explanation,
        }
    
    def __str__(self):
        rstr = []
        rstr.append(f'|POLL{"(multiple choice)|" if self.multiple_choice else "|"}: {self.question}\n')
        rstr.append('Options:\n')
        for i, option in enumerate(self.options):
            rstr.append(f"{i+1}. {option}")
        return rstr
    
class ChatWrapper():
    def __init__(self, chat_id: str, chat_name: str, **kwargs):
        self.id: str = str(chat_id)
        self.chat_id = self.id
        self.chat_name: str = chat_name

        self.custom_instructions: str = kwargs.get('custom_instructions', '')
        self.chance: int = kwargs.get('chance', tools.Tool.CHANCE)
        self.max_tokens: int = kwargs.get('max_tokens', tools.Tool.MAX_TOKENS)
        self.max_response_tokens: int = kwargs.get('max_response_tokens', tools.Tool.MAX_RESPONSE_TOKENS)
        self.frequency_penalty: float = kwargs.get('frequency_penalty', tools.Tool.FREQUENCY_PENALTY)
        self.presence_penalty: float = kwargs.get('presence_penalty', tools.Tool.PRESENCE_PENALTY)

    def to_dict(self):
        return {
            'id': self.chat_id,
            'chat_name': self.chat_name,
            'custom_instructions': self.custom_instructions,
            'chance': self.chance,
            'max_tokens': self.max_tokens,
            'max_response_tokens': self.max_response_tokens,
            'frequency_penalty': self.frequency_penalty,
            'presence_penalty': self.presence_penalty,
        }