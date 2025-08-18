from typing import Dict, List, Callable, Tuple
import asyncio
import time

import datetime as dt

from core import database, window, wrapper
from events import ref_events, event_bus, system_events
from services import tokenizers, variables, prompt_enum

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
                # k: prompt_enum.PromptEnum class
                # v: PromptReference
                serialized_data[attribute_name] = {k.get_id(): v.id for k, v in attribute_value.items()}
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
        self.model_provider: str = kwargs.get('model_provider', 'openai')

        self.temperature: float = kwargs.get('temperature', 1)

        self.max_tokens: int = kwargs.get('max_tokens', 1000)
        self.max_response_tokens: int = kwargs.get('max_response_tokens', 500)

        self.penalty_supported: bool = kwargs.get('penalty_supported', True)
        self.frequency_penalty: float = kwargs.get('frequency_penalty', 0.1)
        self.presence_penalty: float = kwargs.get('presence_penalty', 0.1)

        self.reasoning: bool = kwargs.get('reasoning', False)
        self.reasoning_effort_supported: bool = kwargs.get('reasoning_effort_supported', True)
        self.reasoning_effort: str = kwargs.get('reasoning_effort', 'minimal')

        self.think_token: str = kwargs.get('think_token', '</think>')
        self.disable_thinking_token: str = kwargs.get('disable_thinking_token', '/no_think')
        self.disable_thinking: bool = kwargs.get('disable_thinking', False)

        self.verbosity_supported: bool = kwargs.get('verbosity_supported', False)
        self.verbosity: str = kwargs.get('verbosity', 'low')

    def get_request(self) -> Dict:
        request = {
            'model': self.model,
            'temperature': self.temperature,
            'max_output_tokens': self.max_response_tokens,
            'tools': self.tools,
            'store': False,
            'tool_choice': 'auto',
            'truncation': 'auto',
        }

        if self.penalty_supported:
            request['frequency_penalty'] = self.frequency_penalty
            request['presence_penalty'] = self.presence_penalty

        if self.reasoning and self.reasoning_effort_supported:
            request['reasoning_effort'] = self.reasoning_effort

        if self.verbosity_supported:
            request['text'] = {'verbosity': self.verbosity}

        return request
    
    def get_special_fields(self) -> Dict:
        special_fields = {}

        special_fields['model_provider'] = self.model_provider

        if self.think_token:
            special_fields['think_token'] = self.think_token

            if self.disable_thinking:
                special_fields['disable_thinking_token'] = self.disable_thinking_token
                special_fields['disable_thinking'] = self.disable_thinking

        return special_fields

    def count_tokens(self, text: str) -> int:
        '''
        Count tokens in the given text using the tokenizer for this model.
        For now assumes everything is gpt-4o
        '''
        return tokenizers.Tokenizer.gpt(text, model='gpt-4o')

@register_reference
class AssistantReference(Reference):
    ASSISTANT_PROPERTIES = ['chat_event_prompt_idx']

    def __init__(self, id: str, **kwargs):
        super().__init__(id=id, **kwargs)

        self.names: List[str] = kwargs.get('names', [self.id.title()])
        self.chat_event_prompt_idx: Dict[prompt_enum.PromptEnum, str] = kwargs.get('chat_event_prompt_idx', {})

    def get_names(self):
        return self.names
    
    def get_prompt_id(self, prompt_enumeration: prompt_enum.PromptEnum) -> str:
        prompt_id = self.chat_event_prompt_idx.get(prompt_enumeration, '')
        return prompt_id

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

    async def add_message(self, chat_id, wrappers, **kwargs) -> window.Window:
        '''
        Add a message to a chat window, returning the window
        '''
        try:
            wdw: window.Window = self.get_window(chat_id, **kwargs)
        except ValueError as e:
            self.bus.emit(system_events.ErrorEvent(error="Can't load chat window", e=e))
            return

        # add to window
        for wrapper in wrappers:
            await wdw.add_message(wrapper)

        # send signal to add to database
        new_message_event = ref_events.NewMessage(chat_id=chat_id, wrappers=wrappers)
        await self.bus.emit(new_message_event)

        return wdw

    async def get_window(self, chat_id: str, **kwargs) -> window.Window:
        # we don't want to load a window without loading the chat
        chat: wrapper.ChatWrapper = await self.get_chat(chat_id, **kwargs)

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
                wdw = window.Window(chat_id, self.start_datetime)
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
        assistant = await self._get_assistant(chat_id)
        if assistant:
            return assistant.get_names()
        return []
    
    async def get_prompt(self, chat_id: str, prompt_enumeration: prompt_enum.PromptEnum) -> str:
        assistant: AssistantReference = await self._get_assistant(chat_id)
        if not assistant:
            return ''
        
        prompt_id = assistant.get_prompt_id(prompt_enumeration)
        prompt = self.prompts.get(prompt_id, '')
        return prompt

    async def get_prompts(self, chat_id: str) -> Dict[prompt_enum.PromptEnum, str]:
        assistant: AssistantReference = await self._get_assistant(chat_id)
        if not assistant:
            return {}

        assistant_prompt_ids: Dict[prompt_enum.PromptEnum, str] = assistant.chat_event_prompt_idx.items()
        prompts: Dict[prompt_enum.PromptEnum, str] = {}

        for prompt_enum_value, prompt_id in assistant_prompt_ids:
            prompt = self.prompts.get(prompt_id, '')
            prompts[prompt_enum_value] = str(prompt)

        return prompts    

    async def get_chance(self, chat_id: str) -> int:
        chat = await self.get_chat(chat_id)
        if chat:
            return chat.chance
        return 0
    
    async def get_request(self, chat_id: str) -> Dict:
        '''
        Gets the main and extra request bodies for the assistant.
        '''
        chat = await self.get_chat(chat_id)
        if not chat:
            return {}

        model: ModelReference = self.models.get(chat.model_id or variables.Variables.DEFAULT_MODEL)
        request = model.get_request()

        return request
    
    async def get_special_fields(self, chat_id: str) -> Dict:
        chat = await self.get_chat(chat_id)
        if not chat:
            return {}
        
        model: ModelReference = self.models.get(chat.model_id or variables.Variables.DEFAULT_MODEL)
        special_fields = model.get_special_fields() if model else {}

        return special_fields

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