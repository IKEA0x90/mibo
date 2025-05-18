import openai
import datetime as dt
import random

from events import event_bus, conductor_events, assistant_events, system_events
from core import database, window, wrapper

def initialize_assistants(db: database.Database, client: openai.OpenAI, bus: event_bus.EventBus, template: dict, start_datetime: dt.datetime):
    '''
    Creates a dictionary of assistants for each chat in the database.
    '''
    assistants = {}

    chats = db.get_all_chats()
    for chat_id, custom_instructions, chance, max_tokens, max_content_tokens in chats:
        kwargs = {
            'chance': chance,
            'max_tokens': max_tokens,
            'max_content_tokens': max_content_tokens
        }
        assistants[chat_id] = Assistant(chat_id, client, bus, custom_instructions, template, start_datetime, kwargs)

    return assistants

class Assistant:
    def __init__(self, chat_id, client, bus, custom_instructions, template, start_datetime, kwargs):
        self.chat_id: str = chat_id
        self.client: openai.OpenAI = client
        self.bus: event_bus.EventBus = bus
        self.custom_instructions: str = custom_instructions
        self.system_message: str = ''
        self.template: dict = template

        self.messages = window.Window(chat_id, start_datetime)
        
        self.death_timer = -1
        self.last_reply = -1

        self._load(kwargs)
        self._register()

    def _load(self, kwargs):
        self.system_message = self.template.get('instructions', '')
        self.model = self.template.get('model', 'gpt-4.1')
        self.temperature = self.template.get('temperature', 0.95)
        
        self.tools = self.template.get('tools', [])

        self.chance = kwargs.get('chance', 5)
        self.max_tokens = kwargs.get('max_tokens', 3000)
        self.max_content_tokens = kwargs.get('max_content_tokens', 1500)

        self.frequency_penalty = kwargs.get('frequency_penalty', 0.1)
        self.presence_penalty = kwargs.get('presence_penalty', 0.1)

        self.assistant_object = {
            'model': self.model,
            'temperature': self.temperature,
            'max_tokens': self.max_tokens,
            'frequency_penalty': self.frequency_penalty,
            'presence_penalty': self.presence_penalty,
            'tools': self.tools,
        }

    def _register(self):
        self.bus.register(conductor_events.AssistantRequest, self._process_request)
        self.bus.register(conductor_events.MessagePush, self._prepare)
        
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
        pass

    async def _trigger_completion(self, event: conductor_events.AssistantRequest):
        '''
        Makes a json request from self.window.transform_messages()
        Checks if messages requires a reply.
        If so, make a copy of self.assistant_object and add the message to it.
        Then, call self.client.chat.completions.create() with the json request.
        If the reply 
        '''
        pass