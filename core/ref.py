from typing import Dict, List
import os
import json
import inspect
import asyncio

from core import database, wrapper
from events import db_events, event_bus

default_chat_events = {
    "welcome": "default"
}

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
            if attribute_name.startswith('_'):
                continue
            
            # skip methods and callable objects
            if callable(attribute_value):
                continue
                
            # skip id and type since id becomes the key and type is determined from filename
            if attribute_name in ('id', 'type'):
                continue
                
            serialized_data[attribute_name] = attribute_value
        
        return serialized_data
    
    @staticmethod
    def from_dict(reference_data, reference_type):
        '''
        Create a reference instance from a dictionary. Thanks Copilot for this one.
        '''

        if not isinstance(reference_data, dict):
            raise ValueError('from_dict expects a dictionary')

        # look up the reference class by type name
        reference_class = REFERENCE_REGISTRY.get(reference_type)
        if reference_class is None:
            raise ValueError(f"Unknown reference type: {reference_type}")

        # determine which parameters are required by the class constructor
        constructor_signature = inspect.signature(reference_class.__init__)
        required_parameters = []
        
        for parameter_name, parameter_info in constructor_signature.parameters.items():
            # skip 'self' and variadic parameters
            if parameter_name in ('self',):
                continue
            if parameter_info.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL):
                continue
            
            # parameter is required if it has no default value
            if parameter_info.default is inspect._empty:
                required_parameters.append(parameter_name)

        # prepare constructor arguments, excluding the 'type' field
        constructor_kwargs = {key: value for key, value in reference_data.items() if key != 'type'}

        # verify all required parameters are present
        missing_parameters = [param for param in required_parameters if param not in constructor_kwargs]
        if missing_parameters:
            raise ValueError(f"Missing required fields for type '{reference_type}': {', '.join(missing_parameters)}")

        return reference_class(**constructor_kwargs)

class ModelReference(Reference):
    def __init__(self, id: str, supported_fields: List[str], **kwargs):
        super().__init__(id=id, **kwargs)

        self.supported_fields = supported_fields

        self.base_url = kwargs.get('base_url', '')
        self.local = kwargs.get('local', False)

        self.temperature = kwargs.get('temperature', 1)

        self.max_tokens = kwargs.get('max_tokens', 1000)
        self.max_response_tokens = kwargs.get('max_response_tokens', 500)

        self.penalty_supported = kwargs.get('penalty_supported', True)
        self.frequency_penalty = kwargs.get('frequency_penalty', 0.1)
        self.presence_penalty = kwargs.get('presence_penalty', 0.1)

        self.reasoning = kwargs.get('reasoning', False)
        self.reasoning_supported = kwargs.get('reasoning_supported', True)
        self.reasoning_effort = kwargs.get('reasoning_effort', 'medium')

        self.think_token = kwargs.get('think_token', '</think>')
        self.disable_thinking_token = kwargs.get('disable_thinking_token', '/no_think')
        self.disable_thinking = kwargs.get('disable_thinking', False)

class AssistantReference(Reference):
    def __init__(self, id: str, **kwargs):
        super().__init__(id=id, **kwargs)

        self.names = kwargs.get('names', [self.id.title()])
        self.chat_events = kwargs.get('chat_events', default_chat_events)
        self._prompt = ''

    def get_names(self):
        return self.names

class Ref:
    def __init__(self, bus: event_bus.EventBus, db_path: str = 'memory', ref_path: str = 'references'):
        self.bus: event_bus.EventBus = bus
        self.db: database.Database = database.Database(self.bus, db_path)
        self.ref_path: str = ref_path

        self.chats: Dict[str, wrapper.ChatWrapper] = {}

        self.assistants: Dict[str, AssistantReference] = {}
        self.models: Dict[str, ModelReference] = {}

        self._prepare()

    def _prepare(self):
        '''
        Prepare the ref.
        '''
        self.db.initialize_sync()
        self.load_sync()

    def _register(self):
        '''
        Register bus events
        '''
        self.bus.register(db_events.NewChatAck, self._add_chat)   

    def _add_chat(self, event: db_events.NewChatAck):
        chat = event.chat
        if chat and isinstance(chat, wrapper.ChatWrapper):
            chat_id = chat.id
            self.chats[chat_id] = chat

    def _get_assistant(self, chat_id: str) -> AssistantReference:
        '''
        Gets an AssistantReference object for the given chat id. 
        '''
        chat = self.chats.get(chat_id)
        if not chat:
            return None
        


    def get_assistant_names(self, chat_id: str) -> List[str]:
        assistant: str = self.chats.get(chat_id)

        if assistant:
            assistant: AssistantReference = self.assistants.get(assistant)

        if assistant:
            return assistant.get_names()

        return []
    
    def get_assistant_prompt(self, chat_id: str) -> str:
        assistant: str = self.chats.get(chat_id)



    def save_sync(self):
        '''
        Save all reference collections to JSON files in the references directory.
        Each reference type gets its own file: {type_name}s.json
        Example: 'model' references are saved to 'models.json'
        References are saved as dictionaries id : reference format under a root key matching the plural type name.
        '''
        os.makedirs(self.ref_path, exist_ok=True)

        for reference_type, reference_class in REFERENCE_REGISTRY.items():
            # skip base Reference class
            if reference_class is Reference or not reference_type:
                continue

            collection_attribute_name = f"{reference_type}s"
            reference_collection = getattr(self, collection_attribute_name, None)
            
            if reference_collection is None:
                setattr(self, collection_attribute_name, {})
                reference_collection = {}

            if not isinstance(reference_collection, dict):
                continue

            serialized_references = {}
            for reference_id, reference_object in reference_collection.items():
                if isinstance(reference_object, Reference):
                    serialized_references[reference_id] = reference_object.to_dict()

            # wrap in object with plural type name as key
            output_data = {collection_attribute_name: serialized_references}

            output_file_path = os.path.join(self.ref_path, f"{reference_type}s.json")
            with open(output_file_path, 'w', encoding='utf-8') as output_file:
                json.dump(output_data, output_file, indent=2, ensure_ascii=False)

    def load_sync(self):
        '''
        Load all reference collections from JSON files in the references directory.
        Each reference type is loaded from its corresponding file: {type_name}s.json
        If files don't exist, they are created with empty collections.
        Corrupted files are automatically reset to empty collections.
        References is a dictionary of id : reference
        Type is determined from filename.
        '''

        os.makedirs(self.ref_path, exist_ok=True)

        # create empty JSON files for any missing reference types
        for reference_type, reference_class in REFERENCE_REGISTRY.items():
            if reference_class is Reference or not reference_type:
                continue
                
            collection_attribute_name = f"{reference_type}s"
            expected_file_path = os.path.join(self.ref_path, f"{reference_type}s.json")
            if not os.path.exists(expected_file_path):
                with open(expected_file_path, 'w', encoding='utf-8') as new_file:
                    json.dump({collection_attribute_name: {}}, new_file)

        for filename in os.listdir(self.ref_path):
            if not filename.endswith('.json'):
                continue
                
            # extract reference type from filename (e.g., 'models.json' -> 'model')
            plural_type_name = filename[:-5]  # remove '.json'
            if not plural_type_name.endswith('s'):
                continue

            reference_type = plural_type_name[:-1]  # remove trailing 's'
            collection_attribute_name = f"{reference_type}s"

            # verify this is a known reference type
            reference_class = REFERENCE_REGISTRY.get(reference_type)
            if reference_class is None or reference_class is Reference:
                continue

            file_path = os.path.join(self.ref_path, filename)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as input_file:
                    raw_data = json.load(input_file)
            except json.JSONDecodeError:
                raw_data = {collection_attribute_name: {}}
                with open(file_path, 'w', encoding='utf-8') as reset_file:
                    json.dump(raw_data, reset_file)

            if not isinstance(raw_data, dict):
                raw_data = {collection_attribute_name: {}}

            # get the references from the root key
            references_data = raw_data.get(collection_attribute_name, {})
            
            loaded_references = {}
            
            if isinstance(references_data, dict):
                for reference_id, reference_dict in references_data.items():
                    if not isinstance(reference_dict, dict):
                        continue
                    
                    try:
                        reference_instance = Reference.from_dict(reference_dict, reference_type)
                        loaded_references[str(reference_instance.id)] = reference_instance

                    except (ValueError, TypeError):
                        continue

            setattr(self, collection_attribute_name, loaded_references)

    async def save(self):
        await asyncio.to_thread(self.save_sync)

    async def load(self):
        await asyncio.to_thread(self.load_sync)

    async def initialize(self):
        '''
        Re-initialize the ref after the app starts.
        '''
        await self.db.initialize()

    async def close(self):
        '''
        Close the database connection.
        '''
        await self.db.close()