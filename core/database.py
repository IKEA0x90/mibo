import os
import asyncio
import aiosqlite
import sqlite3
import sys

import datetime as dt

from uuid import uuid4
from typing import List
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
            
        self.bus.register(conductor_events.WrapperPush, self._add_wrapper)   
        self.bus.register(db_events.MemoryRequest, self._handle_memory_request)
        
        self._handlers_registered = True

    async def _insert(self, content: wrapper.Wrapper) -> str:
        '''
        Inserts a wrapper linked to an existing chat.
        Does so in a way that doesn't need any future changes.
        '''
        parent_dict = content.to_parent_dict()
        parent_fields = list(parent_dict.keys())
        parent_values = list(parent_dict.values())

        parent_sql = f'INSERT INTO wrappers ({", ".join(parent_fields)}) VALUES ({", ".join(["?"]*len(parent_fields))})'

        # Surely, all english words that mean multiple are just the word with 's' at the end 
        child_table = f"{content.type}s"

        child_dict = content.to_child_dict()
        child_fields = list(child_dict.keys())
        child_values = list(child_dict.values())

        child_sql = f'INSERT INTO {child_table} (sql_id, {", ".join(child_fields)}) VALUES (?, {", ".join(["?"]*len(child_fields))})'

        async with self._lock:
            async with self.conn.cursor() as cursor:
                await cursor.execute('BEGIN')
                try:
                    await cursor.execute(parent_sql, parent_values)
                    sql_id = cursor.lastrowid

                    await cursor.execute(child_sql, [sql_id] + child_values)

                    await self.conn.commit()
                except Exception:
                    await self.conn.rollback()
                    raise

        return content.id 
    
    async def _add_wrapper(self, event: conductor_events.WrapperPush):
        '''
        Add a wrapper to the database.
        '''
        chat_id: str = ''
        try:
            wrappers: List[wrapper.Wrapper] = event.wrapper_list
            if not wrappers:
                return

            message = wrappers[0]
            chat_id = message.chat_id
            chat_name = getattr(message, 'chat_name', '') or ''

            # ensure chat exists
            async with self.conn.cursor() as cursor:
                await cursor.execute('SELECT * FROM chats WHERE chat_id = ?', (chat_id,))
                row = await cursor.fetchone()

            if not row:
                await self.insert_chat(chat_id, chat_name)
                chat = wrapper.ChatWrapper(
                    chat_id=chat_id, chat_name=chat_name,
                    custom_instructions='', chance=tools.Tool.CHANCE,
                    max_context_tokens=tools.Tool.MAX_TOKENS, max_response_tokens=tools.Tool.MAX_RESPONSE_TOKENS,
                    frequency_penalty=tools.Tool.FREQUENCY_PENALTY, presence_penalty=tools.Tool.PRESENCE_PENALTY
                )

            else:
                chat = wrapper.ChatWrapper(
                    chat_id=row['chat_id'], chat_name=row['chat_name'],
                    custom_instructions=row['custom_instructions'], chance=row['chance'],
                    max_tokens=row['max_tokens'], max_response_tokens=row['max_response_tokens'],
                    frequency_penalty=row['frequency_penalty'], presence_penalty=row['presence_penalty'],
                )

            # pre-save images, assign paths before insert
            for w in wrappers:
                if isinstance(w, wrapper.ImageWrapper):
                    if not w.image_path:
                        self._save_image(w)

            for w in wrappers:
                if isinstance(w, wrapper.Wrapper):
                    await self._insert(w)
            
            # we're finished
            await self.bus.emit(db_events.NewChatAck(chat=chat, event_id=event.event_id))

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error=f'Failed to add a message to the database.', e=e, tb=tb, event_id=event.event_id, chat_id=chat_id))
    
    @staticmethod
    def _generate_schemas():
        return [
            f'''
            CREATE TABLE IF NOT EXISTS chats (
                chat_id              TEXT PRIMARY KEY,
                chat_name            TEXT NOT NULL DEFAULT '',
                custom_instructions  TEXT NOT NULL DEFAULT '',
                chance               INTEGER NOT NULL DEFAULT {tools.Tool.CHANCE},
                max_tokens           INTEGER NOT NULL DEFAULT {tools.Tool.MAX_TOKENS},
                max_response_tokens  INTEGER NOT NULL DEFAULT {tools.Tool.MAX_RESPONSE_TOKENS},
                frequency_penalty    FLOAT NOT NULL DEFAULT {tools.Tool.FREQUENCY_PENALTY},
                presence_penalty     FLOAT NOT NULL DEFAULT {tools.Tool.PRESENCE_PENALTY},
                timestamp            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            ''',

            '''
            CREATE TABLE IF NOT EXISTS wrappers (
                sql_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id   TEXT NOT NULL,
                chat_id       TEXT NOT NULL,
                wrapper_type  TEXT NOT NULL,
                datetime      TIMESTAMP NOT NULL,
                tokens        INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE
            );
            ''',

            '''
            CREATE TABLE IF NOT EXISTS messages (
                sql_id    INTEGER PRIMARY KEY,
                role      TEXT NOT NULL,
                user      TEXT NOT NULL,
                message   TEXT NOT NULL,
                reply_id  INTEGER,
                FOREIGN KEY (sql_id) REFERENCES wrappers (sql_id) ON DELETE CASCADE
            );
            ''',

            '''
            CREATE TABLE IF NOT EXISTS images (
                sql_id         INTEGER PRIMARY KEY,
                x              INTEGER NOT NULL,
                y              INTEGER NOT NULL,
                image_path     TEXT NOT NULL,
                image_summary  TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (sql_id) REFERENCES wrappers (sql_id) ON DELETE CASCADE
            );
            ''',

            'CREATE INDEX IF NOT EXISTS idx_wrappers_chat_time ON wrappers (chat_id, datetime, sql_id)',
            'CREATE INDEX IF NOT EXISTS idx_wrappers_telegram ON wrappers (chat_id, telegram_id)',
            'CREATE INDEX IF NOT EXISTS idx_wrappers_type ON wrappers (wrapper_type)',
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
        Responds with a MemoryResponse containing wrappers for chat_id
        starting from the most recent entries,
        ordered oldest to newest,
        capped by max_context_tokens.
        '''
        chat_id = event.chat_id
        messages = []

        try:
            async with self.conn.cursor() as cursor:
                await cursor.execute('SELECT max_tokens FROM chats WHERE chat_id = ?', (chat_id,))
                row = await cursor.fetchone()
            max_tokens = row['max_tokens'] if row else tools.Tool.MAX_TOKENS

            # thanks chatgpt
            sql = '''
            WITH ranked AS (
                SELECT
                    w.sql_id,
                    w.telegram_id,
                    w.chat_id,
                    w.wrapper_type,
                    w.datetime,
                    w.tokens,
                    SUM(w.tokens) OVER (
                        PARTITION BY w.chat_id
                        ORDER BY w.datetime DESC, w.sql_id DESC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS running_total
                FROM wrappers AS w
                WHERE w.chat_id = ?
            )
            SELECT sql_id, telegram_id, chat_id, wrapper_type, datetime, tokens
            FROM ranked
            WHERE running_total <= ?
            ORDER BY datetime ASC, telegram_id ASC, sql_id ASC;
            '''

            async with self.conn.cursor() as cursor:
                await cursor.execute(sql, (chat_id, max_tokens))
                parent_rows = await cursor.fetchall()

            if not parent_rows:
                response = db_events.MemoryResponse(chat_id=chat_id, messages=messages, event_id=event.event_id)
                await self.bus.emit(response)
                return

            # split ids by type for child fetches
            msg_sql_ids = [r['sql_id'] for r in parent_rows if r['wrapper_type'] == 'message']
            img_sql_ids = [r['sql_id'] for r in parent_rows if r['wrapper_type'] == 'image']

            msg_map = {}
            img_map = {}

            async with self.conn.cursor() as cursor:
                if msg_sql_ids:
                    question_marks = ','.join('?' for _ in msg_sql_ids) # the correct number of ? for the query
                    await cursor.execute(f'''
                        SELECT sql_id, role, user, message, reply_id
                        FROM message_wrappers
                        WHERE sql_id IN ({question_marks})
                    ''', msg_sql_ids)
                    for row in await cursor.fetchall():
                        msg_map[row['sql_id']] = row

                if img_sql_ids:
                    question_marks = ','.join('?' for _ in img_sql_ids)
                    await cursor.execute(f'''
                        SELECT sql_id, x, y, image_path, image_summary
                        FROM image_wrappers
                        WHERE sql_id IN ({question_marks})
                    ''', img_sql_ids)
                    for row in await cursor.fetchall():
                        img_map[row['sql_id']] = row

            for row_data in parent_rows:
                wrapper_type = row_data['wrapper_type']
                datetime_raw = row_data['datetime']

                if isinstance(datetime_raw, dt.datetime):
                    datetime = datetime_raw.astimezone(dt.timezone.utc)
                else:
                    try:
                        datetime = dt.datetime.fromisoformat(datetime_raw)
                        if datetime.tzinfo is None:
                            datetime = datetime.replace(tzinfo=dt.timezone.utc)
                        else:
                            datetime = datetime.astimezone(dt.timezone.utc)
                    except Exception:
                        datetime = dt.datetime.now(dt.timezone.utc)

                if wrapper_type == 'message':
                    child = msg_map.get(row_data['sql_id'])
                    if not child:
                        continue

                    m = wrapper.MessageWrapper(
                        message_id=row_data['telegram_id'], chat_id=row_data['chat_id'],
                        role=child['role'], user=child['user'],
                        message=child['message'], ping=False,
                        reply_id=child['reply_id'], datetime=datetime, 
                        tokens=row_data['tokens']
                    )
                    messages.append(m)

                elif wrapper_type == 'image':
                    child = img_map.get(row_data['sql_id'])
                    if not child:
                        continue

                    im = wrapper.ImageWrapper(
                        image_id=row_data['telegram_id'], chat_id=row_data['chat_id'],
                        x=child['x'], y=child['y'],
                        image_bytes=None, image_path=child['image_path'],
                        image_summary=child['image_summary'], datetime=datetime, 
                        tokens=row_data['tokens'],
                    )
                    messages.append(im)

                else:
                    continue

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error=f'Failed to retrieve your memory.', e=e, tb=tb, event_id=event.event_id, chat_id=chat_id))
            messages = []

        finally:
            response = db_events.MemoryResponse(chat_id=chat_id, messages=messages, event_id=event.event_id)
            await self.bus.emit(response)

    def _save_image(self, image: wrapper.ImageWrapper) -> str:
        '''
        Saves the image to disk and assigns its path to the wrapper
        '''
        path = f'{self.image_path}/{image.chat_id}'
        os.makedirs(path, exist_ok=True)
        filepath = f'{path}/{uuid4().hex}.jpg'

        with open(filepath, 'wb') as f:
            f.write(image.data or b'')

        image.filepath = filepath