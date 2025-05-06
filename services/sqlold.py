
import shutil
import sqlite3

import datetime
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Union

from wowsuchsmart_telegram import window


class Database:
    async def connect(self) -> None:
        """Connect to the SQLite database asynchronously."""

    
    async def close(self) -> None:
        """Close the database connection asynchronously."""
        if self.conn:
            await self.conn.close()
            self.conn = None
            self.cursor = None
    

    

    
    async def ensure_group_exists(self, group_id: str) -> None:
        """Create group if it doesn't exist."""
        await self.ensure_initialized()
        try:
            # Using parameterized query to prevent SQL injection
            await self.cursor.execute(
                "INSERT OR IGNORE INTO groups (group_id) VALUES (?)",
                (group_id,)
            )
            await self.conn.commit()
        except Exception as e:
            await self.conn.rollback()
            print(f"Error ensuring group exists: {e}")
            raise
    
    async def save_message_wrapper(self, group_id: str, message_wrapper, token_count: int) -> str:
        """
        Save a MessageWrapper to the database asynchronously.
        
        Args:
            group_id: The group ID the message belongs to
            message_wrapper: The MessageWrapper object to save
            token_count: Number of tokens in the message
            
        Returns:
            The message ID (UUID) of the saved message
        """
        await self.ensure_initialized()
        try:
            # Generate a unique ID for the message
            message_id = str(uuid.uuid4())
            
            # First ensure the group exists
            await self.ensure_group_exists(group_id)
            
            # Extract values from the wrapper
            role = message_wrapper.role
            username = message_wrapper.user
            content = message_wrapper.content
            need_to_finish = message_wrapper.need_to_finish
            
            # Extract optional text content
            content_text = content.optional_text
            
            # Using parameterized queries to prevent SQL injection
            await self.cursor.execute(
                """
                INSERT INTO messages 
                (message_id, group_id, role, username, content_text, token_count, need_to_finish) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (message_id, group_id, role, username, content_text, token_count, need_to_finish)
            )
            
            # Save sticker if present
            if content.optional_sticker:
                await self.cursor.execute(
                    "INSERT INTO stickers (message_id, key_emoji, sticker_pack) VALUES (?, ?, ?)",
                    (message_id, content.optional_sticker.key_emoji, content.optional_sticker.sticker_pack)
                )
            
            # Save image if present
            if content.optional_image:
                await self.cursor.execute(
                    "INSERT INTO images (message_id, image_url) VALUES (?, ?)",
                    (message_id, content.optional_image.image_url)
                )
            
            await self.conn.commit()
            return message_id
        
        except Exception as e:
            # Roll back any changes if an error occurs
            await self.conn.rollback()
            print(f"Error saving message: {e}")
            raise
    
    async def get_messages_for_group(self, group_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieve messages for a specific group asynchronously.
        
        Args:
            group_id: The group ID to fetch messages for
            limit: Maximum number of messages to retrieve
            
        Returns:
            List of message dictionaries with their associated content
        """
        await self.ensure_initialized()
        try:
            messages = []
            
            # Using parameterized queries to prevent SQL injection
            await self.cursor.execute(
                """
                SELECT m.message_id, m.role, m.username, m.content_text, m.token_count, 
                       m.need_to_finish, m.created_at
                FROM messages m
                WHERE m.group_id = ?
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (group_id, limit)
            )
            
            rows = await self.cursor.fetchall()
            
            for row in rows:
                message = dict(row)
                message_id = row['message_id']
                
                # Get sticker if exists
                await self.cursor.execute(
                    "SELECT key_emoji, sticker_pack FROM stickers WHERE message_id = ?",
                    (message_id,)
                )
                sticker_row = await self.cursor.fetchone()
                if sticker_row:
                    message['sticker'] = dict(sticker_row)
                
                # Get image if exists
                await self.cursor.execute(
                    "SELECT image_url FROM images WHERE message_id = ?",
                    (message_id,)
                )
                image_row = await self.cursor.fetchone()
                if image_row:
                    message['image'] = dict(image_row)
                
                messages.append(message)
            
            return messages
        
        except Exception as e:
            print(f"Error retrieving messages: {e}")
            raise
    
    async def get_context_by_message_id(self, group_id: str, message_id: str, token_limit: int) -> List[Dict[str, Any]]:
        """
        Retrieve messages for a specific group up to a token limit, starting from a given message_id.

        Args:
            group_id: The group ID to fetch messages for.
            message_id: The starting message ID.
            token_limit: The maximum number of tokens to retrieve.

        Returns:
            List of message dictionaries with their associated content.
        """
        await self.ensure_initialized()
        try:
            messages = []
            total_tokens = 0

            # Fetch messages ordered by creation time, starting from the given message_id
            await self.cursor.execute(
                """
                SELECT m.message_id, m.role, m.username, m.content_text, m.token_count, 
                       m.need_to_finish, m.created_at
                FROM messages m
                WHERE m.group_id = ? AND m.created_at <= (
                    SELECT created_at FROM messages WHERE message_id = ?
                )
                ORDER BY m.created_at DESC
                """,
                (group_id, message_id)
            )

            rows = await self.cursor.fetchall()

            for row in rows:
                if total_tokens + row['token_count'] > token_limit:
                    break

                message = dict(row)
                current_message_id = row['message_id']

                # Get sticker if exists
                await self.cursor.execute(
                    "SELECT key_emoji, sticker_pack FROM stickers WHERE message_id = ?",
                    (current_message_id,)
                )
                sticker_row = await self.cursor.fetchone()
                if sticker_row:
                    message['sticker'] = dict(sticker_row)

                # Get image if exists
                await self.cursor.execute(
                    "SELECT image_url FROM images WHERE message_id = ?",
                    (current_message_id,)
                )
                image_row = await self.cursor.fetchone()
                if image_row:
                    message['image'] = dict(image_row)

                messages.append(message)
                total_tokens += row['token_count']

            return messages[::-1]  # Reverse to maintain chronological order

        except Exception as e:
            print(f"Error retrieving context: {e}")
            raise
    
    async def get_response_context(self, group_id: str, message_id: str, token_limit: int, response_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve a combined context for a specific group, dividing the token limit between
        the latest messages and messages starting from a response_id.

        Args:
            group_id: The group ID to fetch messages for.
            message_id: The starting message ID for the latest context.
            token_limit: The maximum number of tokens to retrieve.
            response_id: The starting message ID for the response context.

        Returns:
            List of message dictionaries with their associated content.
        """
        await self.ensure_initialized()
        try:
            # Divide the token limit by 2
            half_token_limit = token_limit // 2

            # Get the latest context
            latest_context = await self.get_context_by_message_id(group_id, message_id, half_token_limit)

            # Get the response context
            response_context = await self.get_context_by_message_id(group_id, response_id, half_token_limit)

            # Create a set of message IDs from the latest context for deduplication
            latest_message_ids = {msg['message_id'] for msg in latest_context}

            # Filter out duplicate messages from the response context
            response_context = [msg for msg in response_context if msg['message_id'] not in latest_message_ids]

            # Combine the two contexts
            combined_context = latest_context + response_context

            return combined_context

        except Exception as e:
            print(f"Error retrieving response context: {e}")
            raise
    
    async def reconstruct_message_wrapper(self, message_data: Dict[str, Any]):
        """
        Convert database message data back to a MessageWrapper object.
        
        Args:
            message_data: Dictionary with message data from the database
            
        Returns:
            Reconstructed MessageWrapper object
        """
        # Create content wrapper with optional components
        content = window.ContentWrapper()
        
        # Add text if present
        if 'content_text' in message_data and message_data['content_text']:
            content.optional_text = message_data['content_text']
        
        # Add sticker if present
        if 'sticker' in message_data:
            content.optional_sticker = window.StickerWrapper(
                key_emoji=message_data['sticker']['key_emoji'],
                sticker_pack=message_data['sticker']['sticker_pack']
            )
        
        # Add image if present
        if 'image' in message_data:
            content.optional_image = window.ImageWrapper(
                image_url=message_data['image']['image_url']
            )
        
        # Create and return the message wrapper
        return window.MessageWrapper(
            role=message_data['role'],
            user=message_data['username'],
            content=content,
            need_to_finish=message_data['need_to_finish']
        )
    
    async def delete_messages_for_group(self, group_id: str) -> int:
        """
        Delete all messages for a specific group.
        
        Args:
            group_id: The group ID to delete messages for
            
        Returns:
            Number of deleted messages
        """
        await self.ensure_initialized()
        try:
            # Using parameterized queries to prevent SQL injection
            await self.cursor.execute("SELECT COUNT(*) FROM messages WHERE group_id = ?", (group_id,))
            count = (await self.cursor.fetchone())[0]
            
            await self.cursor.execute("DELETE FROM messages WHERE group_id = ?", (group_id,))
            await self.conn.commit()
            
            return count
        except Exception as e:
            await self.conn.rollback()
            print(f"Error deleting messages: {e}")
            raise
            
    async def add_image(self, image_bytes: bytes, ext: str = "png") -> str:
        """Save image to disk and return the path"""
        # Create directory if it doesn't exist
        content_dir = 'img/content'
        os.makedirs(content_dir, exist_ok=True)
        
        # Generate filename with UUID to avoid clashes
        fname = f"{uuid.uuid4()}.{ext}"
        fpath = os.path.join(content_dir, fname)
        
        # Write the image to disk asynchronously
        async with aiofiles.open(fpath, "wb") as f:
            await f.write(image_bytes)
            
        return fpath

async def cdn_image(image_path):
    """
    Copy an image to a web-accessible location and return a URL.
    The image is automatically deleted after 5 minutes.
    """
    content_dir = '/var/www/html/img/content'
    os.makedirs(content_dir, exist_ok=True)
    
    filename = f'{uuid.uuid4()}{Path(image_path).suffix}'
    dest_path = os.path.join(content_dir, filename)
    
    # Use aiofiles to copy asynchronously
    async with aiofiles.open(image_path, 'rb') as src_file:
        content = await src_file.read()
        async with aiofiles.open(dest_path, 'wb') as dest_file:
            await dest_file.write(content)
    
    async def delete_file():
        await asyncio.sleep(5 * 60)  # 5 minutes
        try:
            os.remove(dest_path)
            print(f'Deleted temporary file: {dest_path}')
        except Exception as e:
            print(f'Failed to delete temporary file {dest_path}: {e}')
    
    # Create task properly
    loop = asyncio.get_running_loop()
    loop.create_task(delete_file())
    
    # Return the URL
    return f'http://cinnamonbun.ru/img/content/{filename}'

async def is_image(message):
    """Check if a Telegram message contains an image."""
    if message.photo:
        return True
    if message.document and message.document.mime_type and message.document.mime_type.startswith('image'):
        return True
    return False

async def parse_link(message):
    """Get image URL from a Telegram message."""
    image_url = None
    if message.photo:
        # Get the largest photo size
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        image_url = file.file_path
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('image'):
        file = await message.bot.get_file(message.document.file_id)
        image_url = file.file_path
    return image_url

async def download_telegram_image(message):
    """Download an image from a Telegram message."""
    if message.photo:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        content = await file.download_as_bytearray()
        return content
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('image'):
        file = await message.bot.get_file(message.document.file_id)
        content = await file.download_as_bytearray()
        return content
    return None