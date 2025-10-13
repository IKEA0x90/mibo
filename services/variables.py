import os
import random

from babel import Locale
from typing import List
from dotenv import load_dotenv

class Variables:
    '''
    Environmental variables.
    '''
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env", ".env")
    load_dotenv(dotenv_path=env_path, override=True)

    TELEGRAM_KEY = os.environ.get('TELEGRAM_KEY', '') # Telegram bot key
    OPENAI_KEY = os.environ.get('OPENAI_KEY', '') # OpenAI API key

    DB_PATH = os.environ.get('DB_PATH', 'memory') # relative path to the database file

    USERNAME = os.environ.get('USERNAME', '') # telegram USERNAME of the bot
    SYSTEM_CHAT = os.environ.get('SYSTEM_CHAT', '') # id of the system chat where all possible notifications are sent to #TODO change to system_user

    LOCAL_API_HOST = os.environ.get('LOCAL_API_HOST', '127.0.0.1') # ip of the local ollama host
    LOCAL_API_PORT = os.environ.get('LOCAL_API_PORT', '8888') # port of the local ollama host

    DEFAULT_ASSISTANT = os.environ.get('DEFAULT_ASSISTANT', 'default') # id of the default assistant, assumed to exist in assistant references
    DEFAULT_MODEL = os.environ.get('DEFAULT_MODEL', 'gpt-4.1') # id (name) of the default model. assumed to exist in model references

    try:
        CHAT_TTL = os.environ.get('CHAT_TTL', 3600) # time it takes for a chat to unload from memory, in minutes
        CHAT_TTL = int(CHAT_TTL)
    except ValueError:
        CHAT_TTL = 3600

    @staticmethod
    def replacers(original: str) -> str:
        '''
        Custom defined replacers for a message.
        Replaces random stuff that I don't like and is easier to change here rather than in the prompt.
        (real homies hate em dashes)
        '''
        message = original.replace('—', ' - ') 

        return message
    
    @staticmethod
    def typing_delay(text: str):
        length = len(text)
        avg_cpm = 800
        jitter_sd = 0.08
        # Ramp from 0 to 0.3 seconds over the first 16 characters
        reaction = random.uniform(0.0, 0.3) * min(length, 16) / 16
        base = (60.0 / avg_cpm) * length
        multiplier = max(0.2, random.gauss(1.0, jitter_sd))
        return max(0.0, reaction + base * multiplier)
    
    @staticmethod
    def get_language_from_locale(language_code: str) -> str:
        '''
        Maps a language code to a language name.
        '''
        try:
            return Locale.parse(language_code).get_display_name(language_code).capitalize()
        except:
            return language_code
        
    @staticmethod
    def parse_text(text: str) -> List[str]:
        '''
        Parse the text for custom delimiters.
        '''
        text = text.strip()
        text_list = text.split('|n|')

        # remove empty strings and whitespace-only strings
        filtered_list = [s for s in text_list if s.strip()]

        return filtered_list