import os
import uuid
import asyncio
import aiosqlite
import sqlite3
import sys

from io import BytesIO
from PIL import Image

from telegram import Message, Update
from telegram.ext import CallbackContext
from typing import List
import datetime as dt

from events import event_bus, db_events, conductor_events, system_events
from core import wrapper
from services import tools

class Database:
    def __init__(self, bus: event_bus.EventBus, db_path: str):
        self.path = db_path
        self.db_path = os.path.join(db_path, 'mibo.db')
        self.image_path = os.path.join(db_path, 'images')

        self.bus = bus
        self.conn = None 
        self._init_done = False
        self._lock = asyncio.Lock()  # Add lock to prevent race conditions

    def get_all_chats(self) -> List[wrapper.ChatWrapper]:
        '''
        Returns all chat IDs and their custom instructions from the database.
        Synchronous method for use during initialization.
        '''
        try:
            # Use synchronous SQLite connection for initial data fetch

            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM chats')
            rows = cursor.fetchall()
            
            conn.close()
            
            return [wrapper.ChatWrapper(row['chat_id'], row['chat_name'],
                                        row['custom_instructions'], row['chance'], 
                                        row['max_context_tokens'], row['max_content_tokens'], row['max_response_tokens'], 
                                        row['frequency_penalty'], row['presence_penalty']) 
                                        for row in rows]
        
        except Exception as e:
            _, _, tb = sys.exc_info()
            self.bus.emit_sync(system_events.ErrorEvent(error="Hmm.. Can't read your group chats from the database.", e=e, tb=tb))
            return []

    async def initialize(self):
        '''
        Connect to the database and create tables if they don't exist
        '''
        try:
            self.conn = await aiosqlite.connect(self.db_path)
            await self.conn.execute('PRAGMA foreign_keys = ON')
            self.conn.row_factory = aiosqlite.Row

            self._register()

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error = 'The database somehow failed to initialize.', e=e, tb=tb))

        async with self._lock:
            if not self._init_done:
                # Note: The 'if not self.conn:' block below might be unreachable
                # if the initial connection setup always succeeds or raises. 
                # it's here for safety??
                if not self.conn:
                    self.conn = await aiosqlite.connect(self.db_path)
                    await self.conn.execute('PRAGMA foreign_keys = ON')
                    self.conn.row_factory = aiosqlite.Row

                cursor = await self.conn.cursor()
                try:
                    await self.create_tables(cursor)
                finally:
                    await cursor.close()

                self._init_done = True
                
    def initialize_sync(self):
        '''
        Synchronous version of initialize for use outside async contexts.
        Connects to the database and creates tables if they don't exist.
        '''
        try:
            # Use a local synchronous connection for table creation
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            self.create_tables_sync(cursor)
            
            conn.commit()
            cursor.close()
            conn.close()
            
            self._init_done = True
        
            self._register()
        
        except Exception as e:
            _, _, tb = sys.exc_info()
            self.bus.emit_sync(system_events.ErrorEvent(error='The database somehow failed to initialize.', e=e, tb=tb))

    def _register(self):
        '''
        Register bus event listeners
        '''
        # Prevent double registration
        if hasattr(self, '_handlers_registered') and self._handlers_registered:
            return
            
        self.bus.register(conductor_events.ImageDownloadRequest, self._image_to_bytes)
        self.bus.register(db_events.ImageSaveRequest, self._save_images)
        self.bus.register(conductor_events.MessagePush, self._add_message)    
        self.bus.register(db_events.MemoryRequest, self._handle_memory_request)
        
        self._handlers_registered = True

    async def _add_message(self, event: conductor_events.MessagePush):
        '''
        Add a message to the database.
        '''
        try:
            message: wrapper.MessageWrapper = event.request
            
            chat = None
            chat_id = message.chat_id
            chat_name = message.chat_name or ''

            async with self.conn.cursor() as cursor:
                await cursor.execute('SELECT * FROM chats WHERE chat_id = ?', (chat_id,))
                row = await cursor.fetchone()

            # if the chat doesn't exist, create it
            if not row: 
                await self.insert_chat(chat_id, chat_name)
                chat = wrapper.ChatWrapper(
                    chat_id=chat_id, chat_name=chat_name,
                    custom_instructions='', chance=tools.Tool.CHANCE,
                    max_context_tokens=tools.Tool.MAX_CONTEXT_TOKENS, max_content_tokens=tools.Tool.MAX_CONTENT_TOKENS, max_response_tokens= tools.Tool.MAX_RESPONSE_TOKENS,
                    frequency_penalty=tools.Tool.FREQUENCY_PENALTY, presence_penalty=tools.Tool.PRESENCE_PENALTY 
                )

            else:
                chat = wrapper.ChatWrapper(
                    chat_id=row['chat_id'], chat_name=row['chat_name'],
                    custom_instructions=row['custom_instructions'], chance=row['chance'],
                    max_context_tokens=row['max_context_tokens'], max_content_tokens=row['max_content_tokens'], max_response_tokens=row['max_response_tokens'],
                    frequency_penalty=row['frequency_penalty'], presence_penalty=row['presence_penalty']
                )

            await self.bus.emit(db_events.NewChatAck(chat=chat, event_id=event.event_id))

            await self._insert(message)

            for content in message.content_list:
                await self._insert(content)

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error=f'Failed to add a message to the database.', e=e, tb=tb, event_id=event.event_id, chat_id=chat_id))

    async def _insert(self, content: wrapper.Wrapper) -> str:
        '''
        Inserts a message linked to an existing chat. Returns message_id.
        Uses the provided datetime, or current time if not provided.
        '''
        content_dict = content.to_dict()
        fields = list(content_dict.keys())
        values = list(content_dict.values())

        sql = f'INSERT INTO messages ({', '.join(fields)}) VALUES ({', '.join(['?']*len(fields))})'

        async with self._lock:
            async with self.conn.cursor() as cursor:
                await cursor.execute(sql, values)
                await self.conn.commit()
            
        return content.id
             
    async def _image_to_bytes(self, event: conductor_events.ImageDownloadRequest):
        '''
        Download all image files (photos or image documents) from a Telegram message 
        and respond with a list of byte arrays.
        '''
        try:
            update: Update = event.update
            context: CallbackContext = event.context

            chat = update.effective_chat
            chat_id = chat.id

            message: Message = update.effective_message
            file_bytes = []

            # Handle photos - only get the largest size (last in the list)
            if message.photo:
                largest_photo = message.photo[-1]  # Last photo is the largest
                file = await context.bot.get_file(largest_photo.file_id)
                photo_bytes = await file.download_as_bytearray()
                file_bytes.append(photo_bytes)

            # Handle single image document
            elif message.document and message.document.mime_type and message.document.mime_type.startswith('image/'):
                file = await context.bot.get_file(message.document.file_id)
                doc_bytes = await file.download_as_bytearray()
                file_bytes.append(doc_bytes)

            # Always emit ImageSaveRequest, even with empty file_bytes
            request = db_events.ImageSaveRequest(chat_id=str(message.chat.id), file_bytes=file_bytes, event_id=event.event_id)
            await self.bus.emit(request)
        
        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error='Failed to download image.', e=e, tb=tb, event_id=event.event_id, chat_id=chat_id))

    async def _save_images(self, event: db_events.ImageSaveRequest):
        '''
        Compresses the image to jpg
        Resizes the bigger size to 768px, keeping the other scaled with it, using bicubic interpolation.
        Saves image to disk and returns the path.
        Makes a uuid4.hex uid for each image, making that the item name. 
        Also makes a list of the same images in base64 strings.
        '''
        try:
            chat_id = event.chat_id
            file_bytes = event.file_bytes
            
            # path = os.path.join(self.image_path, chat_id)
            # os.makedirs(path, exist_ok=True)

            images: List[wrapper.ImageWrapper] = []
            
            async def process_image(img_bytes):
                def sync_process():

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
                        if img.mode not in ('RGB', 'L'):
                            img = img.convert('RGB')

                        # no need to save it probably, 
                        # img.save(filepath, format='JPEG', quality=85)
                        
                        # Generate base64 representation
                        buffered = BytesIO()
                        img.save(buffered, format='JPEG', quality=85)
                        img_bytes = buffered.getvalue()
                        
                    wrap = wrapper.ImageWrapper(new_width, new_height, img_bytes)
                    return wrap
                
                return await asyncio.to_thread(sync_process)
            
            images = await asyncio.gather(*[process_image(img_bytes) for img_bytes in file_bytes])
            
            # Send the response event with the paths and base64 strings
            response = db_events.ImageResponse(chat_id=chat_id, images=images, event_id=event.event_id)
            await self.bus.emit(response)

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error="Couldn't save one of the images to disk.", e=e, tb=tb, event_id=event.event_id, chat_id=chat_id))
    
    @staticmethod
    def _generate_schemas():
        return [
            f'''
            CREATE TABLE IF NOT EXISTS chats (
                chat_id           TEXT PRIMARY KEY,
                chat_name TEXT NOT NULL DEFAULT '',
                custom_instructions TEXT NOT NULL DEFAULT '',
                chance            INTEGER NOT NULL DEFAULT {tools.Tool.CHANCE},
                max_context_tokens INTEGER NOT NULL DEFAULT {tools.Tool.MAX_CONTENT_TOKENS},
                max_content_tokens INTEGER NOT NULL DEFAULT {tools.Tool.MAX_CONTENT_TOKENS},
                max_response_tokens INTEGER NOT NULL DEFAULT {tools.Tool.MAX_RESPONSE_TOKENS},
                frequency_penalty FLOAT NOT NULL DEFAULT {tools.Tool.FREQUENCY_PENALTY},
                presence_penalty  FLOAT NOT NULL DEFAULT {tools.Tool.PRESENCE_PENALTY},
                timestamp        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            ''',

            '''
            CREATE TABLE IF NOT EXISTS messages (
                message_id   TEXT PRIMARY KEY,
                chat_id      TEXT NOT NULL,
                role         TEXT NOT NULL,
                user         TEXT NOT NULL,
                message      TEXT NOT NULL,
                reply_id     TEXT DEFAULT NULL,
                datetime     TIMESTAMP NOT NULL,
                context_tokens       INTEGER DEFAULT 0,
                content_tokens       INTEGER DEFAULT 0,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE
            );
            ''',

            '''
            CREATE TABLE IF NOT EXISTS images (
                image_id    TEXT PRIMARY KEY,
                x           INTEGER NOT NULL,
                y           INTEGER NOT NULL,
                image_bytes     BLOB NOT NULL,
                image_summary   TEXT DEFAULT '',
                content_tokens  INTEGER NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages (message_id) ON DELETE CASCADE
            );
            ''',

            'CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages (chat_id)',
            'CREATE INDEX IF NOT EXISTS idx_images_message_id ON images (message_id)',

            '''
            CREATE TABLE IF NOT EXISTS reactions (
                reaction_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id      TEXT NOT NULL,
                user            TEXT NOT NULL,
                reaction        TEXT NOT NULL,
                datetime        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(message_id) REFERENCES messages(message_id) ON DELETE CASCADE
            );
            '''
        ]

    async def create_tables(self, cursor) -> None: # Accepts cursor
        '''
        Create the tables asynchronously.
        '''
        try:
            schemas = self._generate_schemas()
            for schema in schemas:
                await cursor.execute(schema)
            await self.conn.commit()

        except Exception as e:
            await self.conn.rollback() # Consider rollback on the main connection
            _, _, tb = sys.exc_info()
            self.bus.emit(system_events.ErrorEvent(error='Failed to create database tables.', e=e, tb=tb))

    def create_tables_sync(self, cursor): # Accepts cursor
        '''
        Synchronous version of create_tables for use with sqlite3.
        '''
        try:
            schemas = self._generate_schemas()
            for schema in schemas:
                cursor.execute(schema)
            cursor.connection.commit()

        except Exception as e:
            _, _, tb = sys.exc_info()
            self.bus.emit_sync(system_events.ErrorEvent(error='Failed to create database tables.', e=e, tb=tb))

    async def close(self):
        '''
        Closes the async database connection if it exists.
        '''
        if self.conn:
            await self.conn.close()
            self.conn = None
            # self.cursor = None # Removed shared cursor

    async def _handle_memory_request(self, event: db_events.MemoryRequest):
        '''
        Responds to MemoryRequest with a MemoryResponse containing all messages for the chat_id, ordered by datetime ascending.
        '''
        chat_id = event.chat_id
        messages = []

        try:
            async with self.conn.cursor() as cursor:
                await cursor.execute('SELECT * FROM messages WHERE chat_id = ? ORDER BY datetime ASC', (chat_id,))
                rows = await cursor.fetchall()
            
            for row_data in rows: 
                
                message = wrapper.MessageWrapper(
                    chat_id=row_data['chat_id'],
                    message_id=row_data['message_id'],
                    role=row_data['role'],
                    user=row_data['user'],
                    message=row_data['message'],
                    ping=False,
                    reply_id=row_data['reply_id'] or '',
                    datetime=row_data['datetime'],
                )

                try:
                    # Ensure datetime is timezone-aware UTC
                    datetime_string = row_data['datetime']
                    if isinstance(datetime_string, str):
                        datetime = dt.datetime.fromisoformat(datetime_string)
                    elif isinstance(datetime_string, dt.datetime):
                        datetime = datetime_string
                    else: # Fallback for unexpected types
                        datetime = dt.datetime.now(dt.timezone.utc)

                    if datetime.tzinfo is None:
                        datetime = datetime.replace(tzinfo=dt.timezone.utc)
                    else:
                        datetime = datetime.astimezone(dt.timezone.utc)
                    message.datetime = datetime

                except ValueError: # Fallback for parsing errors
                    message.datetime = dt.datetime.now(dt.timezone.utc)

                messages.append(message)

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error=f'Failed to retrieve your memory.', e=e, tb=tb, event_id=event.event_id, chat_id=chat_id))
            messages = []

        finally:
            response = db_events.MemoryResponse(chat_id=chat_id, messages=messages, event_id=event.event_id)
            await self.bus.emit(response)