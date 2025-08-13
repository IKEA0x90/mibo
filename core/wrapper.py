import base64
import tiktoken
import re

import datetime as dt
from typing import Any, Dict, List, Optional

from services import variables
from core import ref

WRAPPER_REGISTRY = {}
def register_wrapper(cls):
    type_name = cls.__name__.replace('Wrapper', '').lower() # type is the class name without 'Wrapper'
    cls.type = type_name # assign type to the class
    WRAPPER_REGISTRY[type_name] = cls
    return cls

@register_wrapper
class Wrapper():
    def __init__(self, id: str, chat_id: str, datetime: dt.datetime = None, **kwargs):
        self.id: str = str(id)
        self.chat_id: str = str(chat_id)
        self.type = self.__class__.type # assign type to the instance

        self.tokens: int = kwargs.get('tokens', 0)

        self.role: str = kwargs.get('role', 'assistant')
        self.user: str = kwargs.get('user', variables.Variables.MIBO)

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
            'role': self.role,
            'user': self.user,
        }
    
    @classmethod
    def from_db_row(cls, parent_row, child_row):
        combined_data = {**parent_row, **child_row}
        
        constructor_params = {
            'id': combined_data.get('telegram_id'),
            'chat_id': combined_data.get('chat_id'),
            'datetime': combined_data.get('datetime'),
            'tokens': combined_data.get('tokens', 0),
            'role': combined_data.get('role', 'assistant'),
            'user': combined_data.get('user', variables.Variables.MIBO),
        }
    
        constructor_params.update(child_row)
        inst = cls(**constructor_params)
        
        return inst

    def to_child_dict(self) -> Dict[str, Any]:
        raise NotImplementedError("Subclasses should implement this method to return child-specific data.")
    
    @classmethod
    def get_child_fields(cls):
        raise NotImplementedError("Subclasses should implement this method to return child field names.")

    def calculate_tokens(self):
        raise NotImplementedError("Subclasses should implement this method to calculate tokens.")

@register_wrapper
class MessageWrapper(Wrapper):
    def __init__(self, id: str, chat_id: str, message: str = '', ping: bool = True, **kwargs):
        super().__init__(id, chat_id, **kwargs)
        
        self.chat_name: str = kwargs.get('chat_name', '')

        self.reactions: List[str] = kwargs.get('reactions', [])

        self.message: str = message or ''

        self.ping: bool = ping

        self.reply_id: str = kwargs.get('reply_id', None)
        self.quote_start: int = kwargs.get('quote_start', None)
        self.quote_end: int = kwargs.get('quote_end', None)

        self.think = kwargs.get('think', '')

    def to_child_dict(self):
        return {
            'message': self.message,
            'reply_id': self.reply_id,
            'quote_start': self.quote_start,
            'quote_end': self.quote_end,
            'think': self.think,
        }
    
    @classmethod
    def get_child_fields(cls):
        return ['message', 'reply_id', 'quote_start', 'quote_end', 'think']

    def __str__(self):
        return f'{self.user}: {self._remove_prefix(self.message)}'

    @staticmethod
    def _remove_prefix(text: str) -> str:
        '''
        Removes the prefixed name from the text if it exists
        '''
        prefix = variables.Variables.MIBO_MESSAGE  # 'mibo:'
        pattern = rf'^(?:{prefix.rstrip()}\s+)+'
        text2 = text.strip()

        if re.match(pattern, text, flags=re.IGNORECASE):
            text2 = re.sub(pattern, '', text, flags=re.IGNORECASE)

        return text2
    
    def calculate_tokens(self, model='gpt-4o'):
        encoding = tiktoken.encoding_for_model(model)
        tokens = len(encoding.encode(str(self)))
        return tokens

@register_wrapper
class ImageWrapper(Wrapper):
    def __init__(self, id: str, chat_id: str, x: int, y: int, image_bytes: Optional[bytes] = None, image_path: Optional[str] = None, **kwargs):
        super().__init__(id, chat_id, **kwargs)
        self.x = x or 0
        self.y = y or 0

        self.image_bytes: bytes = image_bytes or b''
        self.image_path: str = image_path or ''

        self.image_summary: str = kwargs.get('image_summary', '')
        
        self.tokens_precalculated: int = kwargs.get('tokens', False)
        self.summary_tokens: int = kwargs.get('summary_tokens', 0)

        self.detail: str = kwargs.get('detail', 'low')

    def calculate_tokens(self):
        if self.detail == 'low':
            return 85

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
    
    @classmethod
    def get_child_fields(cls):
        return ['x', 'y', 'image_path', 'image_summary']

@register_wrapper  
class PollWrapper(Wrapper):
    def __init__(self, id: str, chat_id: str, question: str, options: List[str], multiple_choice: bool, correct_option_idx: int = 0, explanation: str = '', **kwargs):
        super().__init__(id, chat_id, **kwargs)

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
    
    @classmethod
    def get_child_fields(cls):
        return ['question', 'options', 'multiple_choice', 'correct_option_idx', 'explanation']

    def __str__(self):
        rstr = []
        rstr.append(f'|POLL|{self.question}\n')
        rstr.append(f'Options {"(multiple choice)|" if self.multiple_choice else "|"}:\n')
        for i, option in enumerate(self.options):
            rstr.append(f"{i+1}. {option}")
        return rstr
    
class ChatWrapper():
    def __init__(self, id: str, name: str, **kwargs):
        self.id: str = str(id)
        self.chat_id = self.id

        self.name = str(name)
        self.chat_name: str = name

        self.chance: int = kwargs.get('chance', 5)
        self.assistant: 

    def to_dict(self):
        return {
            'id': self.chat_id,
            'chat_name': self.chat_name,
            'chance': self.chance,
        }