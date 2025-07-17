import datetime as dt
import asyncio

from typing import List, Dict, Deque
from collections import deque
from copy import deepcopy

from core import wrapper
from events import assistant_events, event_bus

class Window():
    def __init__(self, chat_id: str, start_datetime: dt.datetime, template: dict, max_tokens: int):
        self.chat_id: str = chat_id
        self.start_datetime: dt.datetime = start_datetime

        self.tokens: int = 0

        self._lock = asyncio.Lock()
        self._stale_buffer: Deque[wrapper.Wrapper] = deque()

        self.max_tokens: int = max_tokens
        
        self.messages: Deque[wrapper.Wrapper] = deque()
        self.ready: bool = False

    def __len__(self):
        return len(self.messages)
    
    def __getitem__(self, idx):
        return self.messages[idx]
    
    def __delitem__(self, idx):
        del self.messages[idx]

    def contains(self, message: wrapper.Wrapper) -> bool:
        '''
        Checks if the window contains a message with the same id.
        '''
        return any(msg.id == message.id for msg in self.messages)

    async def override(self, message: wrapper.Wrapper) -> None:
        '''
        Clears the windows and adds the message.
        '''
        async with self._lock:
            self.messages.clear()
            self.tokens = 0
            self.ready = True

            await self._insert_live_message(message)

    async def add_message(self, event_id: str, message: wrapper.Wrapper, bus: event_bus.EventBus) -> bool:
        '''
        Adds a message to the window. 
        returns True if the window now contains the latest context.
        '''
        async with self._lock:
            is_new = message.datetime >= self.start_datetime

            # always keep the message for context
            await self._insert_live_message(message)

            # if this is the first non‑stale message after start‑up
            # mark the window ready and broadcast.
            if not self.ready and is_new:
                self.ready = True

            # assistant should respond only for new messages *after* ready.
            return is_new and self.ready

    async def _insert_live_message(self, message: wrapper.Wrapper) -> None:
        message_tokens = message.tokens or message.calculate_tokens()
        inserted = False

        # Assume messages arrive mostly in order
        if not self.messages or message.datetime >= self.messages[-1].datetime:
            self.messages.append(message)
            inserted = True

        else:
            for i in range(len(self.messages) - 1, -1, -1):
                if message.datetime >= self.messages[i].datetime:
                    self.messages.insert(i + 1, message)
                    inserted = True
                    break

            if not inserted:
                self.messages.appendleft(message)

        self.tokens += message_tokens
        await self._trim_excess_tokens()

    async def _trim_excess_tokens(self) -> None:
        while self.tokens > self.max_tokens and self.messages:
            oldest_msg = self.messages.popleft()
            oldest_tokens = await oldest_msg.tokens
            self.tokens -= oldest_tokens

    async def transform_messages(self) -> List[Dict[str, object]]:
        '''
        Transforms the context messages into a json compatible with OpenAI chat completions API.
        Preserves both text and images as content blocks.
        '''
        messages = []
        message: wrapper.Wrapper

        for message in self.messages:
            content = []

            if isinstance(message, wrapper.MessageWrapper):
                message: wrapper.MessageWrapper
                text = message.message if message.role == 'assistant' else str(message)
                if text:
                    content.append({"type": "text", "text": text})

            elif isinstance(message, wrapper.ImageWrapper):
                message: wrapper.ImageWrapper
                base64 = message.get_base64()
                if base64:
                    content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{base64}"})
                else:
                    content.append({"type": "text", "text": f"|IMAGE|{message.image_summary or '|IMAGE|Image content not available.'}"})

            # For OpenAI chat completions, each message is a dict with 'role' and 'content'
            m = {"role": message.role, "content": content}
            
            messages.append(m)

        return messages