import json
import os
import openai
import random
import asyncio
import traceback

from events import event_bus
from core import database, window

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
        self.messages.initialize()