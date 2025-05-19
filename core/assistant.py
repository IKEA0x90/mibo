import openai
import datetime as dt
import random

from copy import copy
from typing import List, Dict

from events import event_bus, conductor_events, assistant_events, system_events
from core import database, window, wrapper

def initialize_assistants(db: database.Database, client: openai.OpenAI, bus: event_bus.EventBus, template: dict, start_datetime: dt.datetime):
    '''
    Creates a dictionary of assistants for each chat in the database.
    '''
    assistants = {}

    chats = db.get_all_chats()
    chat: wrapper.ChatWrapper
    for chat in chats:
        chat_id = chat.chat_id
        assistants[chat_id] = Assistant(chat_id, client, bus, template, start_datetime, chat)

    return assistants

class Assistant:
    def __init__(self, chat_id, client, bus, template, start_datetime, chat):
        self.chat_id: str = chat_id
        self.client: openai.OpenAI = client
        self.bus: event_bus.EventBus = bus
        self.system_message: str = ''
        self.template: dict = template
        self.chat: wrapper.ChatWrapper = chat
        
        self.death_timer = -1
        self.last_reply = -1

        self._load()

        self.messages = window.Window(chat_id, start_datetime, template, self.max_context_tokens, self.max_content_tokens)

        self._register()

    def _load(self):
        self.system_message = self.template.get('instructions', '')
        self.model = self.template.get('model', 'gpt-4.1')
        self.temperature = self.template.get('temperature', 0.95)
        
        self.tools = self.template.get('tools', [])

        self.custom_instructions = self.chat.custom_instructions
        self.chance = self.chat.chance
        self.max_context_tokens = self.chat.max_context_tokens
        self.max_content_tokens = self.chat.max_content_tokens
        self.max_response_tokens = self.chat.max_response_tokens

        self.frequency_penalty = self.chat.frequency_penalty
        self.presence_penalty = self.chat.presence_penalty

        self.assistant_object = {
            'model': self.model,
            'temperature': self.temperature,
            'max_output_tokens': self.max_response_tokens,
            'frequency_penalty': self.frequency_penalty,
            'presence_penalty': self.presence_penalty,
            'tools': self.tools,
            'instructions': self.system_message,
            'store': False,
            'tool_choice': 'auto',
            'truncation': 'auto',
        }

    def _register(self):
        self.bus.register(conductor_events.AssistantRequest, self._add_message)
        self.bus.register(conductor_events.MessagePush, self._prepare)
        self.bus.register(assistant_events.AssistantDirectRequest, self._trigger_completion)
        
    async def _check_conditions(self, message: wrapper.MessageWrapper) -> bool:
        '''
        First, checks if the window is ready.
        If not, return False. Othewise:
        If a message is a ping, a reply is guaranteed - return True.
        Otherwise, self.chance % chance to reply.
        When a reply happens, call _reply().
        '''
        if not self.messages.ready:
            return False
        if message.ping:
            return True
        chance = random.randint(1, 100)
        if chance <= self.chance:
            return True
        return False

    async def _add_message(self, event: conductor_events.AssistantRequest):
        '''
        Process an assistant request event.
        Adds the message to the window.
        Triggers _trigger_completion().
        '''
        if event.chat_id != self.chat_id:
            return
        
        self.messages.add_message(event.message)
        run = await self._check_conditions(event.message)
        if run:
            # self.death_timer = death_timer
            # self.last_reply = event.message.timestamp

            ev = assistant_events.AssistantDirectRequest(message=event.message,)
            self.bus.emit(assistant_events.AssistantDirectRequest(ev))

    async def _trigger_completion(self, event: conductor_events.AssistantRequest):
        '''
        Makes a json request from self.window.transform_messages()
        Checks if messages requires a reply.
        If so, make a copy of self.assistant_object and add the message to it.
        Then, call self.client.chat.completions.create() with the json request.
        If the reply 
        '''
        message = event.message
        if message.chat_id != self.chat_id:
            return
        
        if not self.messages.ready:
            return
        
        messages: List[Dict] = self.messages.transform_messages()

        if self.custom_instructions:
            messages.append({
                'role': 'developer',
                'content': self.custom_instructions    
            })

        request = copy(self.assistant_object)
        request['messages'] = messages

        try:
            response  = await self.client.chat.completions.create(**request)
            pass

        except Exception as e:
            pass