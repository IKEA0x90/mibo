import os
import uuid
import asyncio
import aiosqlite
import sqlite3
import base64
from io import BytesIO
from PIL import Image

from telegram import Message, Update
from telegram.ext import CallbackContext
from typing import Tuple, List
import datetime as dt

from events import event_bus, db_events, conductor_events, system_events
from core import wrapper

class Database:
    def __init__(self, bus: event_bus.EventBus, db_path: str):
        self.path = db_path
        self.db_path = os.path.join(db_path, 'mibo.db')
        self.image_path = os.path.join(db_path, 'images')

        self.bus = bus

        self.conn = None
        self.cursor = None
        self._init_done = False
        self._lock = asyncio.Lock()  # Add lock to prevent race conditions

    def get_all_chats(self) -> List[Tuple[str, str, int, int, int, int]]:
        '''
        Returns all chat IDs and their custom instructions from the database.
        Synchronous method for use during initialization.
        '''
        try:
            # Use synchronous SQLite connection for initial data fetch

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT chat_id, custom_instructions, chance, max_context_tokens, max_content_tokens, max_response_tokens, frequency_penalty, presence_penalty FROM chats")
            rows = cursor.fetchall()
            
            conn.close()
            
            return [wrapper.ChatWrapper(row['chat_id'], 
                                        row['custom_instructions'], 
                                        row['chance'], row['max_context_tokens'], 
                                        row['max_content_tokens'], row['max_response_tokens'], 
                                        row['frequency_penalty'], row['presence_penalty']) 
                                        for row in rows]
        
        except Exception as e:
            self.bus.emit(system_events.ErrorEvent('Failed to fetch chats.', e))
            return []

    async def initialize(self):
        '''
        Connect to the database and create tables if they don't exist
        '''
        try:
            self.conn = await aiosqlite.connect(self.db_path)
            await self.conn.execute('PRAGMA foreign_keys = ON') # used for intra-table relations
            self.conn.row_factory = aiosqlite.Row # convert rows to dict-like objects
            self.cursor = await self.conn.cursor() # get the object that executes SQL commands

            self._register()

        except Exception as e:
            self.bus.emit(system_events.ErrorEvent('Database cannot be initialized.', e))

        async with self._lock:
            if not self._init_done:
                if not self.conn:
                    await self.connect()
                await self.create_tables()
                self._init_done = True    
                
    async def _register(self):
        '''
        Register bus event listeners
        '''
        self.bus.register(conductor_events.ImageDownloadRequest, self._image_to_bytes)
        self.bus.register(db_events.ImageSaveRequest, self._save_images)
        self.bus.register(conductor_events.MessagePush, self._add_message)    
        
    async def _add_message(self, event: conductor_events.MessagePush):
        '''
        Add a message to the database.
        '''
        try:
            message = event.request
            chat_id = message.chat_id
            message_id = message.content_id
            role = message.role
            username = message.user
            text = message.message
            datetime = message.datetime
            
            token_count = await message.tokens()
            
            db_message_id = await self.insert_message(
                chat_id=chat_id,
                message_id=message_id,
                role=role,
                username=username,
                text=text,
                token_count=token_count,
                datetime=datetime
            )
            
            for content in message.content_list:
                if isinstance(content, wrapper.ImageWrapper):
                    await self.insert_image(
                        message_id=db_message_id,
                        image_id=content.content_id,
                        image_url=content.image_url
                    )
            
        except Exception as e:
            pass
             
    async def _image_to_bytes(self, event: conductor_events.ImageDownloadRequest):
        '''
        Download all image files (photos or image documents) from a Telegram message 
        and respond with a list of byte arrays.
        '''
        try:
            update: Update = event.update
            context: CallbackContext = event.context

            message: Message = update.effective_message
            file_bytes = []

            # Handle photos
            if message.photo:
                for photo_size in message.photo:
                    file = await context.bot.get_file(photo_size.file_id)
                    photo_bytes = await file.download_as_bytearray()
                    file_bytes.append(photo_bytes)

            # Handle single image document
            elif message.document and message.document.mime_type.startswith('image/'):
                file = await context.bot.get_file(message.document.file_id)
                doc_bytes = await file.download_as_bytearray()
                file_bytes.append(doc_bytes)

            # If needed: process via media_group (albums) from a handler
            # PTB handles albums by grouping updates with the same media_group_id
            # You need to manage album logic at a higher level in a handler

            if file_bytes:
                request = db_events.ImageSaveRequest(chat_id=str(message.chat.id), file_bytes=file_bytes)
                await self.bus.emit(request)
        
        except Exception as e:
            self.bus.emit(system_events.ErrorEvent('Failed to download image.', e))
            return 

    async def _save_images(self, event: db_events.ImageSaveRequest):
        '''
        Compresses the image to jpg
        Resizes the bigger size to 1000px, keeping the other scaled with it, using bicubic interpolation.
        Saves image to disk and returns the path.
        Makes a uuid4.hex uid for each image, making that the item name. 
        Also makes a list of the same images in base64 strings.
        '''
        try:
            chat_id = event.chat_id
            file_bytes = event.file_bytes
            
            path = os.path.join(self.image_path, chat_id)
            os.makedirs(path, exist_ok=True)
            images: List[wrapper.ImageWrapper] = []
            
            # Process each image in the file_bytes list
            for img_bytes in file_bytes:
                # Generate a unique filename
                filename = f"{uuid.uuid4().hex}.jpg"
                filepath = os.path.join(path, filename)
                
                # Open and process the image
                with Image.open(BytesIO(img_bytes)) as img:
                    # Resize the image keeping aspect ratio, with max dimension of 768px
                    width, height = img.size
                    max_size = 768 # this size maximizes cost efficiency and quality
                    
                    if width > height and width > max_size:
                        new_width = max_size
                        new_height = int(height * (max_size / width))
                    elif height > max_size:
                        new_height = max_size
                        new_width = int(width * (max_size / height))
                    else:
                        new_width, new_height = width, height
                        
                    # Resize using bicubic interpolation
                    if new_width != width or new_height != height:
                        img = img.resize((new_width, new_height), Image.BICUBIC)
                    
                    # Save the image
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")

                    img.save(filepath, format='JPEG', quality=85)
                    
                    # Generate base64 representation
                    buffered = BytesIO()
                    img.save(buffered, format="JPEG")
                    img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

                    wrap = wrapper.ImageWrapper(new_width, new_height, filepath, img_base64)
            
            # Send the response event with the paths and base64 strings
            response = db_events.ImageResponse(chat_id=chat_id, images=images)
            await self.bus.emit(response)

        except Exception as e:
            self.bus.emit(system_events.ErrorEvent('Failed to save image.', e))
            return
    
    async def create_tables(self) -> None:
        """
        Create the schema for chats, messages and images.

        Assumes `self.cursor` is an async cursor (e.g. from aiosqlite)
        and `self.conn` is the corresponding connection object.
        """
        try:
            # ------------------ chats ------------------
            await self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id           TEXT PRIMARY KEY,
                custom_instructions TEXT NOT NULL DEFAULT '',
                chance            INTEGER NOT NULL DEFAULT 5,
                max_tokens        INTEGER NOT NULL DEFAULT 3000,
                max_content_tokens        INTEGER NOT NULL DEFAULT 1000,
                max_response_tokens        INTEGER NOT NULL DEFAULT 500,
                frequency_penalty FLOAT NOT NULL DEFAULT 0.1,
                presence_penalty  FLOAT NOT NULL DEFAULT 0.1,
                timestamp        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            );
            """)

            # ------------------ messages ------------------
            await self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                message_id   TEXT PRIMARY KEY,
                chat_id      TEXT NOT NULL,
                role         TEXT NOT NULL,
                username     TEXT NOT NULL,
                text         TEXT NOT NULL,
                positive_reactions INTEGER DEFAULT 0,
                negative_reactions INTEGER DEFAULT 0,
                token_count  INTEGER NOT NULL,
                timestamp   TIMESTAMP DEFAULT,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE
            );
            """)

            # ------------------ images ------------------
            await self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS images (
                image_id    TEXT PRIMARY KEY,
                message_id  TEXT NOT NULL,
                image_url   TEXT NOT NULL,
                content_tokens INTEGER NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages (message_id) ON DELETE CASCADE
            );
            """)

            # ----------- helpful indexes -----------
            await self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages (chat_id)"
            )
            await self.cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_images_message_id ON images (message_id)"
            )

            await self.conn.commit()

        except Exception as e:
            await self.conn.rollback()
            print(f"Error creating tables: {e}")
            
            
    async def insert_chat(
        self,
        chat_id: str,
        *,
        custom_instructions: str = "",
        chance: int = 5,
        max_context_tokens: int = 3000,
        max_content_tokens: int = 1500,
        max_response_tokens: int = 500
    ) -> str:
        """
        Inserts a new chat and returns the chat_id.
        """
        chat_id = chat_id or str(uuid.uuid4())

        await self.cursor.execute(
            """
            INSERT INTO chats
            (chat_id, custom_instructions, chance, max_context_tokens, max_content_tokens, max_response_tokens)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                custom_instructions,
                chance,
                max_context_tokens,
                max_content_tokens,
                max_response_tokens,
            ),
        )
        await self.conn.commit()
        return chat_id

    # ---------- 2. create a message ----------
    async def insert_message(
        self,
        chat_id: str,
        message_id: str,
        *,
        role: str,
        username: str,
        text: str,
        token_count: int,
        datetime: dt.datetime) -> str:
        """
        Inserts a message linked to an existing chat. Returns message_id.
        """
        message_id = message_id or str(uuid.uuid4())
        timestamp = timestamp.timestamp()

        await self.cursor.execute(
            """
            INSERT INTO messages
            (message_id, chat_id, role, username, text, token_count, datetime)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                chat_id,
                role,
                username,
                text,
                token_count,
                datetime
            ),
        )
        await self.conn.commit()
        return message_id


    # ---------- 3. add an image to a message ----------
    async def insert_image(
        self,
        message_id: str,
        image_id: str,
        content_tokens: int,
        *,
        image_url: str) -> str:
        """
        Inserts an image row linked to an existing message. Returns image_id.
        """
        image_id = image_id or str(uuid.uuid4())

        await self.cursor.execute(
            """
            INSERT INTO images
            (image_id, message_id, image_url, content_tokens)
            VALUES (?, ?, ?, ?)
            """,
            (
                image_id,
                message_id,
                image_url,
                content_tokens
            ),
        )
        await self.conn.commit()
        return image_id