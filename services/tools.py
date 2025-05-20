import os
from dotenv import load_dotenv
from events import tool_events

load_dotenv(dotenv_path="env/.env", override=False)

class Tool:
    '''
    Handles all tool requests
    '''
    CREATE_IMAGE = 'create_image'
    CREATE_POLL = 'create_poll'
    SEND_STICKER = 'send_sticker'
    CHANGE_PROPERTY = 'change_property'
    MEMORIZE_KEY_INFORMATION = 'memorize_key_information'

    MIBO_ID = os.environ['MIBO_ID']
    CAT_ASSISTANT_ID = os.environ['CAT_ASSISTANT_ID']
    IMAGE_ASSISTANT_ID = os.environ['IMAGE_ASSISTANT_ID']
    POLL_ASSISTANT_ID = os.environ['POLL_ASSISTANT_ID']
    PROPERTY_ASSISTANT_ID = os.environ['PROPERTY_ASSISTANT_ID']
    MEMORY_ASSISTANT_ID = os.environ['MEMORY_ASSISTANT_ID']

    MIBO = 'mibo'
    CAT_ASSISTANT = 'cat_assistant'
    IMAGE_ASSISTANT = 'image_assistant'
    POLL_ASSISTANT = 'poll_assistant'
    PROPERTY_ASSISTANT = 'property_assistant'
    MEMORY_ASSISTANT = 'memory_assistant'

    IMAGE_ASSISTANT_EVENT = tool_events.ToolImageRequest
    POLL_ASSISTANT_EVENT = tool_events.ToolPollRequest
    PROPERTY_ASSISTANT_EVENT = tool_events.ToolPropertyChangeRequest
    MEMORY_ASSISTANT_EVENT = tool_events.ToolMemorizeKeyInformationRequest

    @staticmethod
    def get_event(assistant_type: str):
        if assistant_type == Tool.IMAGE_ASSISTANT:
            return Tool.IMAGE_ASSISTANT_EVENT
        elif assistant_type == Tool.POLL_ASSISTANT:
            return Tool.POLL_ASSISTANT_EVENT
        elif assistant_type == Tool.PROPERTY_ASSISTANT:
            return Tool.PROPERTY_ASSISTANT_EVENT
        elif assistant_type == Tool.MEMORY_ASSISTANT:
            return Tool.MEMORY_ASSISTANT_EVENT
        
    @staticmethod
    async def create_image(prompt: str, ) -> str:
        '''
        Create an image and given 
        '''
        moderation = 'low'
        model="gpt-image-1"

    @staticmethod
    async def create_poll(question: str, options: list, multiple_choice: bool = False):
        pass

    @staticmethod
    async def send_sticker(key_emoji: str):
        pass

    @staticmethod
    async def change_property(property_name: str, value):
        pass

    @staticmethod
    async def memorize_key_information(key: str, information: str):
        pass