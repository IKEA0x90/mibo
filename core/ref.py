from typing import Dict, List
import asyncio
import time

import datetime as dt

from core import database, window, wrapper
from events import ref_events, event_bus, system_events
from services import variables, prompt_enum

REFERENCE_REGISTRY = {}
def register_reference(cls):
    type_name = cls.__name__.replace('Reference', '').lower() # type is the class name without 'Reference'
    cls.type = type_name # assign type to the class
    REFERENCE_REGISTRY[type_name] = cls
    return cls

@register_reference
class Reference:
    def __init__(self, id: str, **kwargs):
        self.id: str = str(id)
        self.type = self.__class__.type # assign type to the instance

    def to_dict(self):
        '''
        Serialize into a dictionary for saving.
        '''
        serialized_data = {}
        
        # include all public instance attributes
        for attribute_name, attribute_value in self.__dict__.items():

            # skip hidden properties, methods, and special properties
            if attribute_name.startswith('_') or callable(attribute_value) or attribute_name == 'type':
                continue

            # handle prompts in a special way
            if hasattr(self, 'ASSISTANT_PROPERTIES') and attribute_name in self.ASSISTANT_PROPERTIES:
                # k: prompt_enum.PromptEnum
                # v: PromptReference
                serialized_data[attribute_name] = {str(k): v.id for k, v in attribute_value.items()}
            else:
                serialized_data[attribute_name] = attribute_value
        
        return serialized_data
    
    @staticmethod
    def from_dict(reference_data, reference_type):
        '''
        Create a reference instance from a dictionary.
        '''

        if not isinstance(reference_data, dict):
            raise ValueError('Reference from_dict expects a dictionary.')

        reference_class = REFERENCE_REGISTRY.get(reference_type)
        if reference_class is None:
            raise ValueError(f"Unknown reference type: {reference_type}")

        if reference_data.get('id') is None:
            raise ValueError('Reference id missing.')

        constructor_kwargs = {key: value for key, value in reference_data.items() if key != 'type'}

        # handle special deserialization for assistant properties
        if reference_type == 'assistant' and hasattr(reference_class, 'ASSISTANT_PROPERTIES'):
            for field in reference_class.ASSISTANT_PROPERTIES:
                if field in constructor_kwargs and isinstance(constructor_kwargs[field], dict):
                    constructor_kwargs[field] = {
                        prompt_enum.PromptEnum(k): v for k, v in constructor_kwargs[field].items()
                    }

        return reference_class(**constructor_kwargs)
    
@register_reference
class ModelReference(Reference):
    def __init__(self, id: str, **kwargs):
        super().__init__(id=id, **kwargs)

        self.base_url: str = kwargs.get('base_url', '')
        self.local: bool = kwargs.get('local', False)

        self.temperature: float = kwargs.get('temperature', 1)

        self.max_tokens: int = kwargs.get('max_tokens', 1000)
        self.max_response_tokens: int = kwargs.get('max_response_tokens', 500)

        self.penalty_supported: bool = kwargs.get('penalty_supported', True)
        self.frequency_penalty: float = kwargs.get('frequency_penalty', 0.1)
        self.presence_penalty: float = kwargs.get('presence_penalty', 0.1)

        self.reasoning: bool = kwargs.get('reasoning', False)
        self.reasoning_effort_supported: bool = kwargs.get('reasoning_effort_supported', True)
        self.reasoning_effort: str = kwargs.get('reasoning_effort', 'medium')

        self.think_token: str = kwargs.get('think_token', '</think>')
        self.disable_thinking_token: str = kwargs.get('disable_thinking_token', '/no_think')
        self.disable_thinking: bool = kwargs.get('disable_thinking', False)

@register_reference
class AssistantReference(Reference):
    ASSISTANT_PROPERTIES = ['chat_event_prompt_idx']

    def __init__(self, id: str, **kwargs):
        super().__init__(id=id, **kwargs)

        self.names: List[str] = kwargs.get('names', [self.id.title()])
        self.chat_event_prompt_idx: Dict[prompt_enum.PromptEnum, PromptReference] = kwargs.get('chat_event_prompt_idx', {})

    def get_names(self):
        return self.names

class PromptReference(Reference):
    def __init__(self, id: str, **kwargs):
        super().__init__(id=id, **kwargs)

        # this is present here but not in other classes due to the confusing nature of prompt reference and prompt enum
        try:
            self.prompt: str = str(kwargs.get('prompt', ''))
        except Exception:
            self.prompt: str = ''

    def __str__(self):
        return self.prompt

class Ref:
    def __init__(self, bus: event_bus.EventBus, db_path: str = 'memory', start_datetime: dt.datetime = None):
        self.bus: event_bus.EventBus = bus
        self.db: database.Database = database.Database(self.bus, db_path)
        self.start_datetime: dt.datetime = start_datetime or dt.datetime.now(dt.timezone.utc)

        self.chats: Dict[str, wrapper.ChatWrapper] = {}
        self.windows: Dict[str, window.Window] = {}

        self.assistants: Dict[str, AssistantReference] = {}
        self.models: Dict[str, ModelReference] = {}
        self.prompts: Dict[str, PromptReference] = {}

        self._prepare()

    def _prepare(self):
        '''
        Prepare the ref.
        '''
        self.db.initialize_sync()
        self._load()

    async def add_message(self, chat_id, wrappers):
        try:
            wdw: window.Window = self.get_window(chat_id)
        except ValueError as e:
            self.bus.emit(system_events.ErrorEvent(error="Can't load chat window", e=e))
            return

        pass

    async def get_window(self, chat_id: str) -> window.Window:
        # we don't want to load a window without loading the chat
        chat: wrapper.ChatWrapper = await self.get_chat(chat_id)

        chat_model: str = chat.model_id or variables.Variables.DEFAULT_MODEL
        model: ModelReference = self.models.get(chat_model)
        if not model:
            raise ValueError(f"Default model doesn't exist")

        # same loading as chat
        wdw = self.windows.get(chat_id)
        if not wdw:
            wdw = await self.db.get_window(chat_id, model.max_tokens)
            if not wdw:
                # create a new window
                wdw = window.Window(self.start_datetime)
                self.windows[chat_id] = wdw

        return wdw

    async def get_chat(self, chat_id: str, **kwargs) -> wrapper.ChatWrapper:
        # from memory
        chat = self.chats.get(chat_id)
        if not chat:
            # from database
            chat = await self.db.get_chat(chat_id)
            if not chat:
                # create it
                chat = wrapper.ChatWrapper(chat_id, **kwargs)
                await self.bus.emit(ref_events.NewChat(chat))
            
            # add to memory
            self.chats[chat_id] = chat

        chat.last_active = time.time()
        chat.in_use = True
        
        return chat

    async def _get_assistant(self, chat_id: str) -> AssistantReference:
        '''
        Gets an AssistantReference object for the given chat id. 
        '''
        chat: wrapper.ChatWrapper = self.chats.get(chat_id)
        if not chat:
            return None

        assistant_id: str = chat.assistant
        if not assistant_id:
            assistant_id = variables.Variables.DEFAULT_ASSISTANT

        assistant_ref: AssistantReference = self.assistants.get(assistant_id)
        return assistant_ref

    async def get_assistant_names(self, chat_id: str) -> List[str]:
        assistant_ref = await self._get_assistant(chat_id)
        if assistant_ref:
            return assistant_ref.get_names()
        return []

    def _load(self):
        '''
        Load all reference collections from the database.
        '''     
        try:
            references_data = self.db.get_references()

            for reference_id, (reference_type, reference_data) in references_data.items():
                if reference_type == 'reference':
                    continue
                elif reference_type not in REFERENCE_REGISTRY:
                    continue

                elif reference_type == 'assistant':
                    reference_object = AssistantReference.from_dict(reference_data, reference_type)
                    self.assistants[reference_id] = reference_object

                elif reference_type == 'model':
                    reference_object = ModelReference.from_dict(reference_data, reference_type)
                    self.models[reference_id] = reference_object

                elif reference_type == 'prompt':
                    reference_object = PromptReference.from_dict(reference_data, reference_type)
                    self.prompts[reference_id] = reference_object

        except Exception as e:
            self.bus.emit_sync(system_events.ErrorEvent(
                error='Failed to load references from database.',
                e=e
            ))
        
    async def initialize(self):
        '''
        Re-initialize the ref after the app starts.
        This performs full async initialization and loading from the database.
        '''
        await self.db.initialize()
        await self._load_async()
        self._register()
        
        self._cleanup_task = asyncio.create_task(self._cleanup())

    async def _cleanup(self):
        while True:
            now = time.time()
            to_delete = []

            for cid, chat in list(self.chats.items()):
                if (now - chat.last_active) > (variables.CHAT_TTL * 60 / 2):

                    if not chat.in_use:
                        to_delete.append(cid)
                    else:
                        chat.in_use = False

            for cid in to_delete:
                del self.chats[cid]

            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break

    async def close(self):
        '''
        Close the database connection and cancel cleanup task.
        '''
        if hasattr(self, '_cleanup_task') and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        await self.db.close()