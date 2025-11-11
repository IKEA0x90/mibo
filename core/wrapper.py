import base64
import tiktoken
import re

import datetime as dt
from typing import Any, Dict, List, Optional

from services import variables

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
        self.user: str = kwargs.get('user', variables.Variables.USERNAME)

        self.reply_id: str = kwargs.get('reply_id', None)

        try:
            self.datetime: dt.datetime = datetime.astimezone(dt.timezone.utc)
        except Exception:
            # if no datetime is provided, assign the oldest possible datetime so ready checks are failed
            self.start_datetime: dt.datetime = dt.datetime.min.replace(tzinfo=dt.timezone.utc)

    def to_parent_dict(self) -> Dict[str, Any]:
        '''
        Common meta row for the parent wrappers table
        '''
        return {
            'telegram_id': self.id,
            'chat_id': self.chat_id,
            'wrapper_type': self.type,
            'datetime': self.datetime,
            'role': self.role,
            'user': self.user,
            'reply_id': self.reply_id,
        }
    
    @classmethod
    def from_db_row(cls, parent_row, child_row):
        combined_data = {**parent_row, **child_row}
        
        constructor_params = {
            'id': combined_data.get('telegram_id'),
            'chat_id': combined_data.get('chat_id'),
            'datetime': combined_data.get('datetime'),
            'role': combined_data.get('role', 'assistant'),
            'user': combined_data.get('user', variables.Variables.USERNAME),
            'reply_id': combined_data.get('reply_id', None),
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

        self.message: str = message or ''
        self.ping: bool = ping
        
        self.reactions: List[str] = kwargs.get('reactions', [])

        self.quote: str = kwargs.get('quote', None)

        self.think = kwargs.get('think', '')
        
        self.group_id: str = kwargs.get('group_id', id)

    def to_child_dict(self):
        return {
            'message': self.message,
            'quote': self.quote,
            'think': self.think,
        }
    
    @classmethod
    def get_child_fields(cls):
        return ['message', 'quote', 'think']

    def __str__(self):
        return f'{self.message}'

    @staticmethod
    def _remove_prefixes(text: str, prefixes: List[str]) -> str:
        '''
        Removes the prefixed name from the text if it exists
        '''
        text2 = text.strip()
        
        # Create a pattern that matches any prefix from the list
        if prefixes:
            # Escape special regex characters and join with OR
            escaped_prefixes = [re.escape(prefix.rstrip()) for prefix in prefixes]
            pattern = rf'^(?:(?:{"|".join(escaped_prefixes)})\s+)+'
            
            if re.match(pattern, text2, flags=re.IGNORECASE):
                text2 = re.sub(pattern, '', text2, flags=re.IGNORECASE)

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
        
        # For linking to parent message/album
        self.group_id: str = kwargs.get('group_id', id)

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
 
class UserWrapper():
    def __init__(self, id: str, **kwargs):
        self.id: str = str(id)

        self.username: str = kwargs.get('username', '')
        self.preferred_name: str = kwargs.get('preferred_name', '')

        self.image_generation_limit: int = kwargs.get('image_generation_limit', 5)
        self.deep_research_limit: int = kwargs.get('deep_research_limit', 3)

        self.utc_offset: int = kwargs.get('utc_offset', 3)
        self.admin_chats: List[str] = kwargs.get('admin_chats', [])

        self.token: str = kwargs.get('token', '')

class ChatWrapper():
    def __init__(self, id: str, **kwargs):
        self.id: str = str(id)
        self.chat_id = self.id

        self.chat_name: str = kwargs.get('name', '')
        self.chat_name = kwargs.get('chat_name', '')

        self.chance: int = kwargs.get('chance', 5)

        self.assistant_id: str = kwargs.get('assistant_id', variables.Variables.DEFAULT_ASSISTANT)
        self.ai_model_id: str = kwargs.get('ai_model_id', variables.Variables.DEFAULT_MODEL)

        self.last_active: float = 0
        self.in_use: bool = False

    def to_dict(self):
        return {
            'id': self.chat_id,
            'chat_name': self.chat_name,
            'chance': self.chance,
            'assistant_id': self.assistant_id,
            'ai_model_id': self.ai_model_id,
        }