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

    async def _extract_metadata(self, message: wrapper.Wrapper) -> wrapper.Wrapper:
        '''
        Extract <key:value> tags from the start of message.message.
        Leaves text after the tags in message.message.
        Returns the message (modified in-place).
        '''
        # Basic guards
        if not isinstance(message, wrapper.MessageWrapper) or not message.message:
            return message

        message_text = message.message
        message_metadata = {}

        # Pattern for a single tag like <key:value>
        tag_pattern = re.compile(r"<([A-Za-z0-9]+):([^>]*)>")

        text_index = 0
        # Consume tags from the very start
        while True:
            tag_match = tag_pattern.match(message_text, text_index)
            if not tag_match:
                break

            tag_key = tag_match.group(1)
            tag_value = tag_match.group(2) if tag_match.group(2) != "" else None

            lowercase_key = tag_key.lower()
            if lowercase_key == "id":
                message_metadata["id"] = tag_value
            elif lowercase_key == "by":
                message_metadata["by"] = tag_value
            elif lowercase_key == "replyto":
                message_metadata["replyTo"] = tag_value
            elif lowercase_key == "quote":
                message_metadata["quote"] = tag_value
            else:
                message_metadata[lowercase_key] = tag_value

            text_index = tag_match.end()

        # Remove the consumed tag block from the start, preserving the rest
        remaining_text = message_text[text_index:]
        if remaining_text.startswith("\n"):
            remaining_text = remaining_text.lstrip("\n")
        message.message = remaining_text

        message.metadata = message_metadata

        # Resolve replyTo into reply_id (safe numeric parsing + bounds checking)
        reply_to_value = message_metadata.get("replyTo")
        if reply_to_value:
            try:
                reply_to_number = int(reply_to_value)
            except (TypeError, ValueError):
                reply_to_number = None

            # If replyTo is exactly one less than the message ID, ignore it
            try:
                current_message_id = int(message_metadata.get("id")) if message_metadata.get("id") else None
            except (TypeError, ValueError):
                current_message_id = None

            if reply_to_number is not None and current_message_id is not None and reply_to_number == current_message_id - 1:
                message_metadata["replyTo"] = None
                message.reply_id = None

            elif reply_to_number is not None and 1 <= reply_to_number <= len(self.messages):
                replied_message = self.messages[reply_to_number - 1]
                message.reply_id = replied_message.id if replied_message else None
            else:
                message.reply_id = None

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
        
        message = await self._extract_metadata(message)

        message_tokens = message.tokens or message.calculate_tokens()
        inserted = False

        # assume messages arrive mostly in order
        try:
            if not self.messages or int(message.id) >= int(self.messages[-1].id):
                self.messages.append(message)
                inserted = True
        except ValueError:
            if not self.messages or (message.datetime + dt.timedelta(seconds=5) >= self.messages[-1].datetime):
                self.messages.append(message)
                inserted = True
        
        if not inserted:
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

    def _prepare_text(self, message: wrapper.MessageWrapper, message_id: int, reply_message_id: int) -> str:
        text = message.message if message.role == 'assistant' else str(message)

        id = message_id
        by = message.user
        quote = message.quote
        
        meta_text = f'<id:{id}><by:{by}>'

        if reply_message_id is not None and reply_message_id != message_id and reply_message_id + 1 != message_id:
            meta_text += f'<replyTo:{reply_message_id}>'

        if quote:
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
        sorted_messages = sorted(self.messages, key=lambda m: m.id)
        telegram_id_to_message_id = {str(msg.id): idx + 1 for idx, msg in enumerate(sorted_messages)}

        grouped_content = {}
        messages = []

        for message_id, message in enumerate(sorted_messages, start=1):
            group_id = message.id

            if group_id not in grouped_content:
                grouped_content[group_id] = {
                    "role": message.role,
                    "content": [],
                    "datetime": message.datetime
                }

            if isinstance(message, wrapper.MessageWrapper):
                if message.message:
                    # Map reply_id (Telegram ID) to message_id if possible
                    reply_message_id = None
                    if message.reply_id:
                        reply_message_id = telegram_id_to_message_id.get(str(message.reply_id))

                    text = self._prepare_text(message, message_id, reply_message_id)
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
                        {"type": "text", "text": f"<image:{message.image_summary or 'Image content not available.'}>"}
                    )

        # Now, sort groups by their first appearance in sorted_messages
        sorted_groups = [grouped_content[k] for k in [msg.id for msg in sorted_messages] if k in grouped_content]

        for group in sorted_groups:
            if group["content"]:
                messages.append({
                    "role": group["role"],
                    "content": group["content"]
                })

        return messages