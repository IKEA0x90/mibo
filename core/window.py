import datetime as dt
import asyncio
import re

from typing import List, Dict, Deque
from collections import deque

from core import wrapper

class Window():
    def __init__(self, chat_id: str, start_datetime: dt.datetime):
        self.chat_id: str = chat_id
        self.start_datetime: dt.datetime = start_datetime

        self.tokens: int = 0
        self.max_tokens: int = 700

        self._lock = asyncio.Lock()
        self._stale_buffer: Deque[wrapper.Wrapper] = deque()
        
        self.messages: Deque[wrapper.Wrapper] = deque()
        self.ready: bool = False

    def set_max_tokens(self, max_tokens: int):
        self.max_tokens = max_tokens

    def __len__(self):
        return len(self.messages)
    
    def __getitem__(self, idx):
        return self.messages[idx]
    
    def __delitem__(self, idx):
        del self.messages[idx]
        
    def __contains__(self, message: wrapper.Wrapper) -> bool:
        '''
        Enables the 'in' keyword to check if the window contains a message with the same id and type.
        '''
        return any((msg.id == message.id and msg.type == message.type) for msg in self.messages)

    def contains(self, message: wrapper.Wrapper) -> bool:
        '''
        Checks if the window contains a message with the same id.
        '''
        return any((msg.id == message.id and msg.type == message.type) for msg in self.messages)

    async def override(self, message: wrapper.Wrapper) -> None:
        '''
        Clears the windows and adds the message.
        '''
        async with self._lock:
            self.messages.clear()
            self.tokens = 0
            self.ready = True

            await self._insert_live_message(message, True)

    async def extract_metadata(self, message: wrapper.Wrapper) -> wrapper.Wrapper:
        """
        Extracts metadata tags from the start of the text in the format =key:value=.
        Returns a metadata dictionary and the remaining text.
        Tags are optional and may not all be present.
        """
        if not isinstance(message, wrapper.MessageWrapper) or not message.message:
            return message
        
        message: wrapper.MessageWrapper
        text = message.message

        metadata = {}
        pattern = r"^(=([a-zA-Z0-9]+):([^=]*)=)+"
        tag_pattern = r"=([a-zA-Z0-9]+):([^=]*)="

        # Find all =key:value= tags at the start
        match = re.match(pattern, text)
        if match:
            tags = re.findall(tag_pattern, match.group(0))
            for key, value in tags:
                if key.lower() == 'id':
                    metadata['id'] = value if value else None
                elif key.lower() == 'by':
                    metadata['by'] = value if value else None
                elif key.lower() == 'replyto':
                    metadata['replyTo'] = value if value else None
                elif key.lower() == 'quote':
                    metadata['quote'] = value if value else None
                else:
                    metadata[key.lower()] = value
            # Remove tags from text
            text = text[match.end():].lstrip('\n')

        message.message = text

        if replyTo := metadata.get('replyTo'):
            replied_message = self.messages[replyTo - 1] 
            message.reply_id = replied_message.id if replied_message else None

        return message

    async def add_message(self, message: wrapper.Wrapper, set_ready: bool = True) -> bool:
        '''
        Adds a message to the window. 
        returns True if the window now contains the latest context.
        '''
        async with self._lock:
            is_new = message.datetime >= self.start_datetime

            # add message
            await self._insert_live_message(message)

            # if this is the first non-stale message after startup
            # mark the window ready and broadcast.
            if not self.ready and is_new and set_ready:
                self.ready = True

            # assistant should respond only for new messages *after* ready.
            return is_new and self.ready

    async def _insert_live_message(self, message: wrapper.Wrapper) -> None:
        if self.contains(message):
            return
        
        message = await self.extract_metadata(message)

        message_tokens = message.tokens or message.calculate_tokens()
        inserted = False

        # assume messages arrive mostly in order
        # add 5 leeway seconds 
        if not self.messages or (message.datetime + dt.timedelta(seconds=5) >= self.messages[-1].datetime):
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
        await self._trim_excess_tokens(self.max_tokens)

    async def _trim_excess_tokens(self, max_tokens: int) -> None:
        while self.tokens > max_tokens and self.messages:
            oldest_msg = self.messages.popleft()
            oldest_tokens = oldest_msg.tokens
            self.tokens -= oldest_tokens

    def _prepare_text(self, message: wrapper.MessageWrapper, message_id: int, reply_to: int) -> str:
        text = message.message if message.role == 'assistant' else str(message)

        metadata = {
            'id': message_id,
            'by': message.user,
            'replyTo': reply_to,
            'quote': message.quote,
        }
        
        meta_text = f'=id:{metadata["id"]}=by:{metadata["by"]}='

        if metadata['replyTo']:
            meta_text += f'replyTo:{metadata["replyTo"]}='

        if metadata['quote']:
            pass # TODO

        text = f'{meta_text}{text}'
        text = text.strip()

        return text

    async def transform_messages(self) -> List[Dict[str, object]]:
        '''
        Transforms the context messages into a json compatible with OpenAI chat completions API.
        Preserves both text and images as content blocks.
        Groups messages with the same group_id.
        '''
        grouped_content = {}
        messages = []

        for message_id, message in enumerate(self.messages, start=1):
            group_id = message.id
            
            if group_id not in grouped_content:
                grouped_content[group_id] = {
                    "role": message.role,
                    "content": [],
                    "datetime": message.datetime
                }
            
            if isinstance(message, wrapper.MessageWrapper):
                if message.message:

                    reply_id = message.reply_id
                    reply_id = reply_id if reply_id and reply_id in self.messages else None

                    text = self._prepare_text(message, message_id, reply_id)
                    if text:
                        grouped_content[group_id]["content"].append({"type": "text", "text": text})
            
            elif isinstance(message, wrapper.ImageWrapper):
                base64 = message.get_base64()
                detail = message.detail
                
                if base64:
                    grouped_content[group_id]["content"].append(
                        {"type": "image_url", "image_url": {'url': f"data:image/jpeg;base64,{base64}", 'detail': detail}}
                    )
                else:
                    grouped_content[group_id]["content"].append(
                        {"type": "text", "text": f"=image={message.image_summary or '=image=Image content not available.'}"}
                    )
        
        sorted_groups = sorted(grouped_content.values(), key=lambda x: x["datetime"])
        
        for group in sorted_groups:
            if group["content"]:
                messages.append({
                    "role": group["role"],
                    "content": group["content"]
                })
        
        return messages