from collections import deque
from collections.abc import MutableSequence
from typing import List, Tuple, Dict, Deque

from core import wrapper

class Window(MutableSequence):
    def __init__(self, chat_id: str, messages: Deque[wrapper.MessageWrapper] = [], kwargs: Dict = {}):
        self.chat_id = chat_id
        self.messages = messages
        self.tokens = 0

        self.max_tokens = kwargs.get('max_tokens', 3000)
        self.max_images = kwargs.get('max_image_tokens', 1000)
        self.max_memory = kwargs.get('max_content_tokens', 1500)
        
        self.messages = deque()

    def __len__(self):
        return len(self.messages)
    
    def __getitem__(self, index):
        if isinstance(index, slice):
            # deque can't slice natively, slice a list copy
            return list(self.messages)[index]
        return self.messages[index]

    def __setitem__(self, index, value):
        if isinstance(index, slice):
            items = list(self.messages)
            items[index] = value
            self.messages = deque(items)
        else:
            self.messages[index] = value

    def __delitem__(self, index):
        if isinstance(index, slice):
            items = list(self.messages)
            del items[index]
            self.messages = deque(items)
        else:
            # rotate target to the left end → popleft → rotate back
            self.messages.rotate(-index)
            self.messages.popleft()
            self.messages.rotate(index)

    async def add_message(self, message: wrapper.MessageWrapper):
        tokens = message.tokens()
        self.tokens += tokens

        if self.tokens > self.max_tokens:
            # remove the oldest message
            self.messages.popleft()
            self.tokens -= self.messages[0].tokens()

    async def _transform_messages(self) -> List[Dict[str, str]]:
        '''
        Transforms the context messages into a json.
        '''
        for message in self.messages:
            pass