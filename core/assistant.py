import json
import os
import openai
import random
import asyncio
import traceback

from events import event_bus, conductor_events, assistant_events, system_events
from core import database, window, wrapper

def initialize_assistants(db: database.Database, client: openai.OpenAI, bus: event_bus.EventBus, template: dict):
    '''
    Creates a dictionary of assistants for each chat in the database.
    '''
    assistants = {}

    chat_ids, custom_intructions = db.get_all_chats()
    for chat, custom_intructions in zip(chat_ids, custom_intructions):
        assistants[chat] = Assistant(chat, client, bus, custom_intructions)

    return assistants

class Assistant:
    def __init__(self, chat_id, client, bus, custom_instructions):
        self.chat_id = chat_id
        self.client = client
        self.bus = bus
        self.custom_instructions = custom_instructions

        self.messages = window.Window(chat_id)
        
        self.death_timer = -1
        self.last_reply = -1

        self._initialize()

    def _register(self):
        self.bus.register(conductor_events.AssistantRequest, self._process_request)

    def _initialize(self):
        self._register()

    async def _process_request(self, event: conductor_events.AssistantRequest):
        pass

    async def _add_message(self, message: wrapper.MessageWrapper):
        '''
        Add a message to the assistant's window.
        '''
        await self.messages.add_message(message)
    
    async def initialize(self):
        '''
        Initialize the assistant with the messages.
        '''
        pass