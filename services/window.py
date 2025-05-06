import os
import tiktoken
import uuid
import asyncio
import aiofiles

from collections import deque
from pydantic import BaseModel
from typing import List, Tuple, Dict, Optional, Union
from telegram import Message as TelegramMessage

class StickerWrapper(BaseModel):
    key_emoji: str
    sticker_pack: str

class ImageWrapper(BaseModel):
    image_url: str

class ContentWrapper(BaseModel):
    optional_text: Optional[str] = None
    optional_sticker: Optional[StickerWrapper] = None
    optional_image: Optional[ImageWrapper] = None

class MessageWrapper(BaseModel):
    role: str
    user: str
    content: ContentWrapper
    need_to_finish: bool = False

class Message:
    def __init__(self, message: TelegramMessage, group_id: str, db):
        self.message = message
        self.group_id = group_id
        self.db = db
        self.message_wrapper = None
        self.token_count = 0
        self.message_id = None
        
    async def initialize(self):
        """Initialize the message asynchronously"""
        self.message_wrapper = await self.parse_message()
        
        # Calculate token count
        if self.message_wrapper.content.optional_text:
            encoder = tiktoken.encoding_for_model("gpt-4o")
            self.token_count = len(encoder.encode(self.message_wrapper.content.optional_text))
        
        # Save message to database
        if self.db and self.group_id:
            await self._save_to_db()
        
        return self

    async def parse_message(self) -> MessageWrapper:
        username = self.message.from_user.full_name if self.message.from_user else "Unknown"
        role = getattr(self.message, 'role', 'user')  # Default to 'user' if role isn't set
        
        content = ContentWrapper()
        
        if hasattr(self.message, 'text') and self.message.text:
            content.optional_text = self.message.text
        
        if hasattr(self.message, 'sticker') and self.message.sticker:
            content.optional_sticker = StickerWrapper(
                key_emoji=self.message.sticker.emoji or "",
                sticker_pack=self.message.sticker.set_name or ""
            )
            
        # Handle image saving
        if await is_image(self.message):
            image_bytes = await download_image(self.message)
            if image_bytes:
                # Save the image to disk
                image_path = self.save_image_to_disk(image_bytes)
                content.optional_image = ImageWrapper(image_url=image_path)
            
        return MessageWrapper(
            role=role,
            user=username,
            content=content
        )
    
    def save_image_to_disk(self, image_bytes: bytes, ext: str = "png") -> str:
        """Save image to disk and return the path"""
        # Create directory if it doesn't exist
        image_dir = os.path.join("img/window", self.group_id)
        os.makedirs(image_dir, exist_ok=True)
        
        # Generate filename with UUID to avoid clashes
        fname = f"{uuid.uuid4()}.{ext}"
        fpath = os.path.join(image_dir, fname)
        
        # Write the image to disk
        loop = asyncio.get_event_loop()
        async def _save_async():
            async with aiofiles.open(fpath, "wb") as f:
                await f.write(image_bytes)
        
        # Run the async operation in the current event loop
        loop.run_until_complete(_save_async())
            
        return fpath
    
    def add_image_to_message(self, image_url: str) -> None:
        """Add image URL to the message wrapper"""
        self.message_wrapper.content.optional_image = ImageWrapper(image_url=image_url)

    async def _save_to_db(self) -> None:
        """Save the message to the database"""
        if self.db and self.group_id:
            try:
                self.message_id = await self.db.save_message_wrapper(
                    self.group_id, 
                    self.message_wrapper, 
                    self.token_count
                )
            except Exception as e:
                print(f"Error saving message to database: {e}")

    def to_json(self) -> str:
        return self.message_wrapper.model_dump_json()

    def to_dict(self) -> dict:
        return self.message_wrapper.model_dump()

class Window:
    def __init__(self, group_id: str, max_tokens: int = 3000, image_dir: str = "img/window", max_images: int = 3):
        self.group_id = group_id
        self.max_tokens = max_tokens
        self._token_count = 0
        self.db = None

        self.messages = deque()
        self.image_urls = deque(maxlen=max_images)

        self.encoder = tiktoken.encoding_for_model("gpt-4o")

        self.image_dir = os.path.join(image_dir, group_id)
        os.makedirs(self.image_dir, exist_ok=True)
        self.max_images = max_images

    def _count_tokens(self, text: str) -> int:
        return len(self.encoder.encode(text))

    def add(self, message) -> None:
        '''
        Add a Message object to the window, counting **only** the raw textual
        content toward the max_tokens budget (wrappers, stickers, images, etc.
        do not consume tokens).
        '''
        text = message.message_wrapper.content.optional_text or ""
        token_len = self._count_tokens(text)

        self.messages.append(message)
        self._token_count += token_len

        # Trim oldest entries until the budget is respected
        while self._token_count > self.max_tokens and self.messages:
            removed = self.messages.popleft()
            removed_text = removed.message_wrapper.content.optional_text or ""
            self._token_count -= self._count_tokens(removed_text)

    @staticmethod
    async def process_context(context: List[MessageWrapper]) -> List[Dict]:
        """Process the context into a format suitable for the OpenAI API"""
        processed = []
        for msg in context:
            content = ""
            if msg.content.optional_text:
                content = msg.content.optional_text
            
            processed.append({
                "role": msg.role,
                "content": content
            })
        return processed

    async def add_image(self, file_bytes: bytes, ext: str = "png") -> str:
        """Save image to disk and return the path. Image handling for local storage."""
        # Create directory if it doesn't exist
        os.makedirs(self.image_dir, exist_ok=True)

        # Generate filename with UUID to avoid clashes
        fname = f"{uuid.uuid4()}.{ext}"
        fpath = os.path.join(self.image_dir, fname)

        # Write the image to disk asynchronously
        async with aiofiles.open(fpath, "wb") as f:
            await f.write(file_bytes)

        return fpath
    
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

    async def get_context(self, message_id: str, response_id: Optional[str] = None, memory_first: bool = True) -> List[MessageWrapper]:
        """
        Retrieve the context for a given message_id, including the message itself
        and previous messages up to the token limit. If response_id is provided,
        split the token limit between the latest context and the response context.

        Args:
            message_id: The ID of the message to start the context retrieval.
            response_id: The ID of the message to start the response context retrieval (optional).
            memory_first: Whether to prioritize memory context over database context (default: True).

        Returns:
            A list of MessageWrapper objects representing the context.
        """
        if not self.db:
            from wowsuchsmart_telegram import sql
            self.db = sql.Database()
            await self.db.ensure_initialized()

        # Use full token limit if no response_id or same as message_id
        token_limit = self.max_tokens
        half_token_limit = token_limit // 2
        
        # Dictionary to track messages by ID for deduplication
        message_dict = {}
        total_tokens = 0
        
        # Step 1: Start with in-memory context if memory_first is True
        if memory_first:
            # Process messages in reverse chronological order (newest first)
            for message in reversed(self.messages):
                if hasattr(message, 'message_id') and message.message_id:
                    text = message.message_wrapper.content.optional_text or ""
                    token_count = self._count_tokens(text)
                    
                    # Determine token limit based on whether we're handling a reply
                    current_limit = half_token_limit if response_id and response_id != message_id else token_limit
                    
                    # Check if adding this message would exceed the token limit
                    if total_tokens + token_count > current_limit:
                        break
                        
                    message_dict[message.message_id] = (message.message_wrapper, token_count)
                    total_tokens += token_count
        
        # Step 2: If not enough context in memory or memory_first is False, load from DB
        db_token_limit = token_limit - total_tokens
        if db_token_limit > 0:
            # Get context from database
            db_context = await self.db.get_context_by_message_id(
                group_id=self.group_id,
                message_id=message_id,
                token_limit=db_token_limit
            )
            
            # Add messages from DB that aren't already in memory context
            for msg_data in db_context:
                msg_id = msg_data['message_id']
                if msg_id not in message_dict:
                    token_count = msg_data['token_count']
                    if total_tokens + token_count <= token_limit:
                        msg_wrapper = await self.db.reconstruct_message_wrapper(msg_data)
                        message_dict[msg_id] = (msg_wrapper, token_count)
                        total_tokens += token_count
                    else:
                        break

        # Step 3: If response_id is provided and different from message_id, get additional context
        response_messages = {}
        if response_id and response_id != message_id:
            # Determine remaining tokens for response context
            response_token_limit = half_token_limit
            response_total_tokens = 0
            
            # First try to get response context from memory
            if memory_first:
                for message in reversed(self.messages):
                    if hasattr(message, 'message_id') and message.message_id:
                        text = message.message_wrapper.content.optional_text or ""
                        token_count = self._count_tokens(text)
                        
                        if response_total_tokens + token_count > response_token_limit:
                            break
                            
                        response_messages[message.message_id] = (message.message_wrapper, token_count)
                        response_total_tokens += token_count
            
            # Then load additional context from the database if needed
            db_response_limit = response_token_limit - response_total_tokens
            if db_response_limit > 0:
                response_db_context = await self.db.get_context_by_message_id(
                    group_id=self.group_id,
                    message_id=response_id,
                    token_limit=db_response_limit
                )
                
                # Add messages from DB that aren't already in memory context
                for msg_data in response_db_context:
                    msg_id = msg_data['message_id']
                    if msg_id not in response_messages and msg_id not in message_dict:
                        token_count = msg_data['token_count']
                        if response_total_tokens + token_count <= response_token_limit:
                            msg_wrapper = await self.db.reconstruct_message_wrapper(msg_data)
                            response_messages[msg_id] = (msg_wrapper, token_count)
                            response_total_tokens += token_count
                        else:
                            break
        
        # Step 4: Combine all messages in chronological order
        # First, add the messages from the main context
        combined_messages = list(message_dict.values())
        
        # Then, add messages from the response context that aren't duplicates
        for msg_id, (msg_wrapper, _) in response_messages.items():
            if msg_id not in message_dict:
                combined_messages.append((msg_wrapper, 0))
        
        # Sort by timestamp if available, otherwise keep the current order
        # This ensures chronological ordering of all messages
        
        # Extract just the message wrappers
        final_context = [msg[0] for msg in combined_messages]
        
        print(f"Final context has {len(final_context)} messages with ~{total_tokens + sum(t for _, t in response_messages.values() if t)} tokens")
        
        return final_context

# Add these functions at the module level
async def is_image(message):
    """Check if a Telegram message contains an image."""
    if message.photo:
        return True
    if message.document and message.document.mime_type and message.document.mime_type.startswith('image'):
        return True
    return False

async def download_image(message):
    """Download image from a Telegram message."""
    if message.photo:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        return await file.download_as_bytearray()
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image"):
        file = await message.bot.get_file(message.document.file_id)
        return await file.download_as_bytearray()
    return None