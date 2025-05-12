import os
import tiktoken
import uuid
import asyncio
import aiofiles

from collections import deque
from typing import List, Tuple, Dict, Deque

from core import wrapper

class Window:
    def __init__(self, chat_id: str, messages: Deque[wrapper.MessageWrapper] = [], kwargs: Dict = {}):
        self.chat_id = chat_id
        self.messages = messages
        self.tokens = 0

        self.max_tokens = kwargs.get('max_tokens', 3000)
        self.max_images = kwargs.get('max_images', 5)
        
        self.messages = deque()
        self.image_urls = deque(maxlen=self.max_images)

    async def _add(self, message) -> None:
        '''
        Add a MessageWrapper to the window
        '''
        pass

    async def process_context(self) -> List[Dict[str, str]]:
        '''
        Makes an openai message list for the bus response
        '''
        processed = []
        for msg in self.messages:
            content = ""
            if msg.content.optional_text:
                content = msg.content.optional_text
            
            processed.append({
                "role": msg.role,
                "content": content
            })

        return processed
    
    def add_image_url(self, image_url: str) -> None:
        """Add an image URL to the context window."""
        if image_url:
            self.image_urls.append(image_url)
            
    def get_image_urls(self) -> List[str]:
        """Get all image URLs in the context window."""
        return list(self.image_urls)

    async def get_content(self) -> Tuple[List[MessageWrapper], List[str]]:
        """Get the message wrappers and list of image paths or URLs."""
        message_wrappers = [msg.message_wrapper for msg in self.messages]
        image_list = list(self.image_urls)
        return message_wrappers, image_list

    def clear(self) -> None:
        """Clear all context including messages and image references."""
        self.messages.clear()
        self.image_urls.clear()
        self._token_count = 0