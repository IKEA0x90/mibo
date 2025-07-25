import os
from dotenv import load_dotenv
from events import tool_events

class Tool:
    '''
    Handles all tool requests
    '''
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env", ".env")
    load_dotenv(dotenv_path=env_path, override=True)

    CREATE_IMAGE = 'create_image'
    CREATE_POLL = 'create_poll'

    MIBO_ID = os.environ['MIBO_ID']
    CAT_ASSISTANT_ID = os.environ['CAT_ASSISTANT_ID']
    IMAGE_ASSISTANT_ID = os.environ['IMAGE_ASSISTANT_ID']
    POLL_ASSISTANT_ID = os.environ['POLL_ASSISTANT_ID']
    PROPERTY_ASSISTANT_ID = os.environ['PROPERTY_ASSISTANT_ID']
    MEMORY_ASSISTANT_ID = os.environ['MEMORY_ASSISTANT_ID']
    STORAGE_MIBO_ID = os.environ['STORAGE_MIBO_ID']

    TELEGRAM_KEY = os.environ['TELEGRAM_KEY']
    OPENAI_KEY = os.environ['OPENAI_KEY']

    DB_PATH = os.environ['DB_PATH']
    MIBO_MESSAGE = os.environ['MIBO_MESSAGE']
    MIBO_PING = os.environ['MIBO_PING']
    SYSTEM_CHAT = os.environ['SYSTEM_CHAT']

    MIBO = os.environ['MIBO']
    CAT_ASSISTANT = os.environ['CAT_ASSISTANT']
    IMAGE_ASSISTANT = os.environ['IMAGE_ASSISTANT']
    POLL_ASSISTANT = os.environ['POLL_ASSISTANT']
    PROPERTY_ASSISTANT = os.environ['PROPERTY_ASSISTANT']
    MEMORY_ASSISTANT = os.environ['MEMORY_ASSISTANT']
    MIBO_RU = os.environ['MIBO_RU']

    try:
        CHANCE = int(os.environ['CHANCE'])
        MAX_TOKENS = int(os.environ['MAX_TOKENS'])
        MAX_RESPONSE_TOKENS = int(os.environ['MAX_RESPONSE_TOKENS'])
        FREQUENCY_PENALTY = float(os.environ['FREQUENCY_PENALTY'])
        PRESENCE_PENALTY = float(os.environ['PRESENCE_PENALTY'])

    except (ValueError, KeyError) as e:
        raise ValueError(f"Error loading environment variables: {e}. Ensure all required variables are set and have valid numeric values.")
    
    IMAGE_ASSISTANT_EVENT = tool_events.ToolImageRequest
    POLL_ASSISTANT_EVENT = tool_events.ToolPollRequest

    @staticmethod
    def get_event(assistant_type: str):
        if assistant_type == Tool.IMAGE_ASSISTANT:
            return Tool.IMAGE_ASSISTANT_EVENT
        elif assistant_type == Tool.POLL_ASSISTANT:
            return Tool.POLL_ASSISTANT_EVENT

    @staticmethod
    def replacers(original: str) -> str:
        '''
        Custom defined replacers for a message.
        Replaces random stuff that I don't like and is easier to change here rather than in the prompt.
        (real homies hate em dashes)
        '''
        message = original.replace('—', ' - ') 

        return message