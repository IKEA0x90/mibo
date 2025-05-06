import os
import uuid
import asyncio
import aiofiles
import aiosqlite

from services import bus

class Database:
    def __init__(self, bus: bus.EventBus, db_path: str):
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        self._init_done = False
        self._lock = asyncio.Lock()  # Add lock to prevent race conditions

    async def initialize(self):
        '''
        Connect to the database and create tables if they don't exist
        '''
        try:
            self.conn = await aiosqlite.connect(self.db_path)
            await self.conn.execute("PRAGMA foreign_keys = ON") # used for intra-table relations
            self.conn.row_factory = aiosqlite.Row # convert rows to dict-like objects
            self.cursor = await self.conn.cursor() # get the object that executes SQL commands

        except Exception as e:
            
            raise

        async with self._lock:
            if not self._init_done:
                if not self.conn:
                    await self.connect()
                await self.create_tables()
                self._init_done = True
    
    async def create_tables(self) -> None:
        '''
        Create the tables if they don't exist
        '''
        try:
            # Create groups table
            await self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                group_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            
            # Create messages table
            await self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                role TEXT NOT NULL,
                username TEXT NOT NULL,
                content_text TEXT,
                token_count INTEGER NOT NULL,
                need_to_finish BOOLEAN NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (group_id) REFERENCES groups (group_id)
            )
            ''')
            
            # Create stickers table
            await self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS stickers (
                message_id TEXT PRIMARY KEY,
                key_emoji TEXT NOT NULL,
                sticker_pack TEXT NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages (message_id) ON DELETE CASCADE
            )
            ''')
            
            # Create images table
            await self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS images (
                message_id TEXT PRIMARY KEY,
                image_url TEXT NOT NULL,
                FOREIGN KEY (message_id) REFERENCES messages (message_id) ON DELETE CASCADE
            )
            ''')
            
            # Create an index on group_id for faster queries
            await self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_group_id ON messages (group_id)')
            
            await self.conn.commit()
        except Exception as e:
            await self.conn.rollback()
            print(f"Error creating tables: {e}")
            raise
