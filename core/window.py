import datetime as dt
import asyncio

from typing import List, Dict, Deque
from collections import deque
from copy import deepcopy

from core import wrapper
from events import assistant_events, event_bus

class Window():
    def __init__(self, chat_id: str, start_datetime: dt.datetime, template: dict, max_context_tokens: int, max_content_tokens: int):
        self.chat_id: str = chat_id
        self.tokens: int = 0
        self.start_datetime: dt.datetime = start_datetime

        self._lock = asyncio.Lock()
        self._stale_buffer: Deque[wrapper.MessageWrapper] = deque()

        self.max_context_tokens: int = max_context_tokens
        self.max_content_tokens: int = max_content_tokens
        
        self.messages: Deque[wrapper.MessageWrapper] = deque()
        self.ready: bool = False

    def __len__(self):
        return len(self.messages)
    
    def __getitem__(self, idx):
        return self.messages[idx]
    
    def __delitem__(self, idx):
        del self.messages[idx]

    async def override(self, message: wrapper.MessageWrapper) -> None:
        '''
        Clears the windows and adds the message.
        '''
        async with self._lock:
            self.messages.clear()
            self.tokens = 0
            self.ready = True

            await self._insert_live_message(message)

    async def add_message(self, event_id: str, message: wrapper.MessageWrapper, bus: event_bus.EventBus) -> bool:
        '''
        Adds a message to the window. 
        returns True if the window now contains the latest context.
        '''
        async with self._lock:
            message_datetime = message.datetime

            if not self.ready:
                if message_datetime < self.start_datetime:
                    self._stale_buffer.append(message)
                    return False
                else:
                    await self._finalize_stale_collection()
                    self.ready = True

                    response = assistant_events.AssistantReadyPush(event_id=event_id)
                    await bus.emit(response)

            await self._insert_live_message(message)
            return True

    async def _finalize_stale_collection(self) -> None:
        # Sort by datetime descending (latest first)
        sorted_buffer = sorted(
            self._stale_buffer,
            key=lambda msg: msg.datetime,
            reverse=True
        )

        token_sum = 0
        for msg in sorted_buffer:
            msg_tokens = await msg.tokens()
            if token_sum + msg_tokens > self.max_context_tokens:
                continue
            self.messages.append(msg)
            token_sum += msg_tokens

        self.tokens = token_sum
        self._stale_buffer.clear()

    async def _insert_live_message(self, message: wrapper.MessageWrapper) -> None:
        message_tokens = await message.tokens()
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
        while self.tokens > self.max_context_tokens and self.messages:
            oldest_msg = self.messages.popleft()
            oldest_tokens = await oldest_msg.tokens()
            self.tokens -= oldest_tokens

    async def transform_messages(self) -> List[Dict[str, object]]:
        '''
        Transforms the context messages into a json compatible with OpenAI chat completions API.
        Preserves both text and images as content blocks.
        '''
        messages = []
        message: wrapper.MessageWrapper
        for message in self.messages:
            content = []

            # Add text as a content block if present
            text = message.message if message.role == 'assistant' else str(message)
            if text:
                content.append({"type": "text", "text": text})

            # Add images as content blocks
            if message.content_list:
                for c in message.content_list:
                    if isinstance(c, wrapper.ImageWrapper):
                        content.append({"type": "image_url", "image_url": f"data:image/jpeg;base64,{c.image_base64}"})

            # For OpenAI chat completions, each message is a dict with 'role' and 'content' (list of blocks)
            m = {"role": message.role, "content": content}
            messages.append(m)

        return messages