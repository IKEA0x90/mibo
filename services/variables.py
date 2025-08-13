import os
from dotenv import load_dotenv

class Variables:
    '''
    Environmental variables.
    '''
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env", ".env")
    load_dotenv(dotenv_path=env_path, override=True)

    TELEGRAM_KEY = os.environ['TELEGRAM_KEY']
    OPENAI_KEY = os.environ['OPENAI_KEY']

    DB_PATH = os.environ['DB_PATH']
    REF_PATH = os.environ['REF_PATH']

    NICKNAME = os.environ['NICKNAME']
    SYSTEM_CHAT = os.environ['SYSTEM_CHAT']

    LOCAL_API_PORT = os.environ['LOCAL_API_PORT']
    LOCAL_API_HOST = os.environ['LOCAL_API_HOST']

    DEFAULT_ASSISTANT = os.environ['DEFAULT_ASSISTANT']
    DEFAULT_MODEL = os.environ['DEFAULT_MODEL']

    @staticmethod
    def replacers(original: str) -> str:
        '''
        Custom defined replacers for a message.
        Replaces random stuff that I don't like and is easier to change here rather than in the prompt.
        (real homies hate em dashes)
        '''
        message = original.replace('—', ' - ') 

        return message