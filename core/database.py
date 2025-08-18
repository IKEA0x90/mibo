import os
import asyncio
import aiosqlite
import sqlite3
import sys
import json
from services import variables
import aiofiles
import datetime as dt

from pathlib import Path
from uuid import uuid4
from typing import List
from events import event_bus, ref_events, system_events
from core import window, wrapper
from services import variables

class Database:
    def __init__(self, bus: event_bus.EventBus, db_path: str):
        self.path = db_path
        self.db_path = os.path.join(db_path, 'mibo.db')
        self.image_path = os.path.join(db_path, 'images')

        self.db_path = Path(self.db_path)
        self.image_path = Path(self.image_path)

        self.bus = bus
        self.conn = None 
        self._init_done = False
        self._lock = asyncio.Lock()  # Add lock to prevent race conditions

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
                    await self._create_tables(cursor)
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
            
            self._create_tables_sync(cursor)
            
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
            
        self.bus.register(ref_events.NewChat, self._insert_chat)
        self.bus.register(ref_events.NewMessage, self._add_message)

        self._handlers_registered = True
    
    async def get_chat(self, chat_id: str) -> wrapper.ChatWrapper:
        '''
        Get a chat by its ID.
        '''
        try:
            async with self.conn.cursor() as cursor:
                await cursor.execute('SELECT * FROM chats WHERE chat_id = ?', (chat_id,))
                row = await cursor.fetchone()

            if row:
                return wrapper.ChatWrapper(id=row['chat_id'], name=row['chat_name'],
                                            chance=row['chance'], assistant_id=row['assistant_id'], model_id=row['model_id'])

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error="Hmm.. Can't read your group chats from the database.", e=e, tb=tb))
            return None

    async def _insert_chat(self, event: ref_events.NewChat):
        '''
        Inserts a new chat and returns the chat_id.
        Uses default assistant and model from environment variables if not specified.
        '''
        chat: wrapper.ChatWrapper = event.chat
        if chat is None or not isinstance(chat, wrapper.ChatWrapper):
            return

        if chat.assistant_id is None:
            chat.assistant_id = variables.Variables.DEFAULT_ASSISTANT
        if chat.model_id is None:
            chat.model_id = variables.Variables.DEFAULT_MODEL

        effective_chat_id = chat.chat_id or str(uuid4())
        chat_name = chat.chat_name
        chance = chat.chance
        assistant_id = chat.assistant_id
        model_id = chat.model_id

        async with self._lock:
            async with self.conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT OR IGNORE INTO chats
                    (chat_id, chat_name, chance, assistant_id, model_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(effective_chat_id), chat_name,
                        chance, assistant_id, model_id
                    ),
                )
                await self.conn.commit()

    async def get_window(self, chat_id: str, model) -> window.Window:
        '''
        Get a chat window, inserting messages up to max_tokens.
        '''
        from core import ref
        wdw: window.Window = window.Window(chat_id, self.start_datetime)
        model: ref.ModelReference = model

        try:
            # TODO actually count tokens for different models instead of assuming everything is openai
            messages = self._get_messages_old(chat_id)
            for msg in messages:
                wdw.add_message(msg, False)

        except Exception as e:
            wdw = window.Window(chat_id, self.start_datetime) # if any errors, just make an empty one
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error="Can't load chat window", e=e, tb=tb))

        finally:
            return wdw


    async def _insert_wrapper(self, content: wrapper.Wrapper) -> str:
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
    
    async def _add_message(self, event: ref_events.NewMessage):
        '''
        Add a wrapper to the database
        '''
        try:
            chat_id: str = event.chat_id
            wrappers: List[wrapper.Wrapper] = event.wrappers
            if not chat_id or not wrappers:
                return

            # pre-save images, assign paths before insert
            for w in wrappers:
                if isinstance(w, wrapper.ImageWrapper):
                    if not w.image_path:
                        filepath = await self._save_image(w)
                        w.image_path = filepath

            for w in wrappers:
                if isinstance(w, wrapper.Wrapper):
                    w.tokens = w.calculate_tokens()
                    await self._insert_wrapper(w)

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error=f'Failed to add a message to the database.', e=e, tb=tb, event_id=event.event_id, chat_id=chat_id))

    @staticmethod
    def _populate_defaults():
        return [
            '''
            INSERT INTO "references" (reference_id, reference_type, data) VALUES
            ('gpt-4.1', 'model', 
                '{
                "model_provider": "openai",
                "temperature": 0.95,
                "max_tokens": 700,
                "max_response_tokens": 500,

                "penalty_disabled": false,
                "frequency_penalty": 0.1,
                "presence_penalty": 0.1,

                "reasoning": false,
                "reasoning_effort_supported": false,
                "reasoning_effort": "",

                "think_token": "",
                "disable_thinking_token": "",
                "disable_thinking": false,

                "verbosity_supported": false,
                "verbosity": "minimal"
                }'
            )
            '''
        ]

    @staticmethod
    def _generate_wrapper_schemas():
        return [
            f'''
            CREATE TABLE IF NOT EXISTS chats (
                chat_id              TEXT PRIMARY KEY,
                chat_name            TEXT NOT NULL DEFAULT '',
                chance               INTEGER NOT NULL DEFAULT 5,
                assistant_id         TEXT NOT NULL DEFAULT '{variables.Variables.DEFAULT_ASSISTANT}',
                model_id             TEXT NOT NULL DEFAULT '{variables.Variables.DEFAULT_MODEL}',
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
                role          TEXT NOT NULL,
                user          TEXT NOT NULL,
                safety_identifier TEXT NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats (chat_id) ON DELETE CASCADE
            );
            ''',

            '''
            CREATE TABLE IF NOT EXISTS messages (
                sql_id    INTEGER PRIMARY KEY,
                message   TEXT NOT NULL,
                reply_id  INTEGER,
                quote     TEXT,
                think     TEXT,
                FOREIGN KEY (sql_id) REFERENCES wrappers (sql_id) ON DELETE CASCADE
            );
            ''',

            '''
            CREATE TABLE IF NOT EXISTS images (
                sql_id         INTEGER PRIMARY KEY,
                x              INTEGER NOT NULL,
                y              INTEGER NOT NULL,
                image_path     TEXT NOT NULL,
                image_summary  TEXT,
                FOREIGN KEY (sql_id) REFERENCES wrappers (sql_id) ON DELETE CASCADE
            );
            ''',

            'CREATE INDEX IF NOT EXISTS idx_wrappers_chat_time ON wrappers (chat_id, datetime, sql_id)',
            'CREATE INDEX IF NOT EXISTS idx_wrappers_telegram ON wrappers (chat_id, telegram_id)',
            'CREATE INDEX IF NOT EXISTS idx_wrappers_type ON wrappers (wrapper_type)',
        ]
    
    @staticmethod
    def _generate_reference_schemas():
        return [
            '''
            CREATE TABLE IF NOT EXISTS "references" (
                sql_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_id  TEXT NOT NULL,
                reference_type TEXT NOT NULL,
                data          TEXT NOT NULL,
                timestamp     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            ''',

            'CREATE UNIQUE INDEX IF NOT EXISTS idx_references_id_type ON "references" (reference_id, reference_type)',
            'CREATE INDEX IF NOT EXISTS idx_references_type ON "references" (reference_type)'
        ]

    async def _create_tables(self, cursor) -> None: # Accepts cursor
        '''
        Create the tables asynchronously.
        '''
        try:
            schemas = self._generate_wrapper_schemas() + self._generate_reference_schemas()
            for schema in schemas:
                await cursor.execute(schema)
            await self.conn.commit()

        except Exception as e:
            await self.conn.rollback() # Consider rollback on the main connection
            _, _, tb = sys.exc_info()
            self.bus.emit(system_events.ErrorEvent(error='Failed to create database tables.', e=e, tb=tb))

    def _create_tables_sync(self, cursor): # Accepts cursor
        '''
        Synchronous version of create_tables for use with sqlite3.
        '''
        try:
            schemas = self._generate_wrapper_schemas() + self._generate_reference_schemas()
            for schema in schemas:
                cursor.execute(schema)
            cursor.connection.commit()

        except Exception as e:
            _, _, tb = sys.exc_info()
            self.bus.emit_sync(system_events.ErrorEvent(error='Failed to create database tables.', e=e, tb=tb))

    async def insert_reference(self, reference) -> str:
        '''
        Inserts a reference into the database.
        Stores the reference ID, type, and serialized data.
        ''' 
        reference_id = reference.id
        reference_type = reference.type
        data = json.dumps(reference.to_dict())
        
        sql = '''
        INSERT OR REPLACE INTO "references"
        (reference_id, reference_type, data)
        VALUES (?, ?, ?)
        '''
        
        async with self._lock:
            async with self.conn.cursor() as cursor:
                await cursor.execute('BEGIN')
                try:
                    await cursor.execute(sql, (reference_id, reference_type, data))
                    await self.conn.commit()
                except Exception:
                    await self.conn.rollback()
                    raise
                    
        return reference_id
        
    def get_references(self):
        '''
        Get all references from the database synchronously.
        Returns a dictionary of {id: (type, data_dict)}
        '''
        sql = 'SELECT reference_id, reference_type, data FROM "references"'
        
        references = {}
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute(sql)
            rows = cursor.fetchall()
            
            for row in rows:
                reference_id = row['reference_id']
                reference_type = row['reference_type']

                try:
                    reference_data = json.loads(row['data'])
                    references[reference_id] = (reference_type, reference_data)

                except json.JSONDecodeError as e:
                    self.bus.emit_sync(system_events.ErrorEvent(
                        error=f'Failed to parse JSON for reference {reference_id}',
                        e=e
                    ))
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            _, _, tb = sys.exc_info()
            self.bus.emit_sync(system_events.ErrorEvent(
                error=f'Failed to get references from database',
                e=e,
                tb=tb
            ))
        
        return references
        
    async def close(self):
        '''
        Closes the async database connection if it exists.
        '''
        if self.conn:
            await self.conn.close()
            self.conn = None
            # self.cursor = None # Removed shared cursor

    async def _get_messages_old(self, chat_id: str):
        '''
        Responds with a MemoryResponse containing wrappers for chat_id
        starting from the most recent entries,
        ordered oldest to newest,
        capped by max_tokens.
        '''
        messages = []

        try:
            async with self.conn.cursor() as cursor:
                await cursor.execute('SELECT max_tokens FROM chats WHERE chat_id = ?', (chat_id,))
                row = await cursor.fetchone()
            max_tokens = row['max_tokens'] if row else variables.Variables.MAX_TOKENS

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
                    w.role,
                    w.user,
                    SUM(w.tokens) OVER (
                        PARTITION BY w.chat_id
                        ORDER BY w.datetime DESC, w.sql_id DESC
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS running_total
                FROM wrappers AS w
                WHERE w.chat_id = ?
            )
            SELECT sql_id, telegram_id, chat_id, wrapper_type, datetime, tokens, role, user
            FROM ranked
            WHERE running_total <= ?
            ORDER BY datetime ASC, telegram_id ASC, sql_id ASC;
            '''

            async with self.conn.cursor() as cursor:
                await cursor.execute(sql, (chat_id, max_tokens))
                parent_rows = await cursor.fetchall()

            if not parent_rows:
                return []

            sql_ids = {}
            for r in parent_rows:
                wrapper_type = r['wrapper_type']
                if wrapper_type not in sql_ids:
                    sql_ids[wrapper_type] = []
                sql_ids[wrapper_type].append(r['sql_id'])

            tables = {}
            async with self.conn.cursor() as cursor:
                for wrapper_type, sql_ids in sql_ids.items():
                    wrapper_class = wrapper.WRAPPER_REGISTRY.get(wrapper_type)
                    if not wrapper_class or not sql_ids:
                        continue
                    
                    table = f"{wrapper_type}s"
                    child_fields = wrapper_class.get_child_fields()

                    placeholder_marks = ','.join('?' for _ in sql_ids)
                    child_query_sql = f"SELECT sql_id, {', '.join(child_fields)} FROM {table} WHERE sql_id IN ({placeholder_marks})"
                    
                    await cursor.execute(child_query_sql, sql_ids)
                    child_rows = await cursor.fetchall()
                    
                    tables[wrapper_type] = {
                        child_row['sql_id']: dict(child_row) for child_row in child_rows
                    }

            for parent_row in parent_rows:
                wrapper_type = parent_row['wrapper_type']
                sql_id = parent_row['sql_id']
                
                wrapper_class = wrapper.WRAPPER_REGISTRY.get(wrapper_type)
                if not wrapper_class:
                    continue 
                    
                child_data = tables.get(wrapper_type, {})
                child_row = child_data.get(sql_id, {})
                
                if not child_row:
                    continue
                
                parent_dict = dict(parent_row)
                
                datetime_raw = parent_dict['datetime']
                if isinstance(datetime_raw, dt.datetime):
                    parsed_datetime = datetime_raw.astimezone(dt.timezone.utc)
                else:
                    try:
                        parsed_datetime = dt.datetime.fromisoformat(datetime_raw)
                        if parsed_datetime.tzinfo is None:
                            parsed_datetime = parsed_datetime.replace(tzinfo=dt.timezone.utc)
                        else:
                            parsed_datetime = parsed_datetime.astimezone(dt.timezone.utc)
                    except Exception:
                        parsed_datetime = dt.datetime.now(dt.timezone.utc)
                
                parent_dict['datetime'] = parsed_datetime
                
                wrapper_instance = wrapper_class.from_db_row(parent_dict, child_row)
                
                if isinstance(wrapper_instance, wrapper.ImageWrapper) and wrapper_instance.image_path:
                    wrapper_instance.image_bytes = await self._load_image(wrapper_instance.image_path)
                
                messages.append(wrapper_instance)

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error=f'Failed to retrieve your memory.', e=e, tb=tb))
            messages = []

        finally:
            return messages

    async def _load_image(self, image_path: str) -> bytes:
        '''
        Load image bytes from the given file path.
        Returns empty bytes if the file doesn't exist or can't be read.
        '''
        try:
            if not image_path or not os.path.exists(image_path):
                return b''
            
            async with aiofiles.open(image_path, 'rb') as f:
                return await f.read()
        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error=f'Failed to load image from {image_path}', e=e, tb=tb))
            return b''

    async def _save_image(self, image: wrapper.ImageWrapper) -> str:
        chat_dir = self.image_path / str(image.chat_id)
        await asyncio.to_thread(chat_dir.mkdir, parents=True, exist_ok=True)

        filepath = chat_dir / f"{uuid4().hex}.jpg"
        data = image.image_bytes or b""

        async with aiofiles.open(filepath, "wb") as f:
            await f.write(data)

        image.image_path = str(filepath)
        return image.image_path