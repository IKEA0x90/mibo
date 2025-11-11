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
    LOCAL_KEY = os.environ.get('LOCAL_KEY', '') # Local API key

    DB_PATH = os.environ.get('DB_PATH', 'memory') # relative path to the database file

    LOCAL_API_HOST = os.environ.get('LOCAL_API_HOST', '127.0.0.1') # ip of the local ollama host
    LOCAL_API_PORT = os.environ.get('LOCAL_API_PORT', '8888') # port of the local ollama host

    USERNAME = os.environ.get('USERNAME', 'itsmiibot') # username of the bot 

    DEFAULT_ASSISTANT = os.environ.get('DEFAULT_ASSISTANT', 'default') # id of the default assistant, assumed to exist in assistant references
    DEFAULT_MODEL = os.environ.get('DEFAULT_MODEL', 'gpt-4.1') # id (name) of the default model. assumed to exist in model references

    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', '') # secret key for JWT tokens
    MIBO_DOMAIN = os.environ.get('MIBO_DOMAIN', 'admin.miibo.ru') # domain where the admin panel is hosted

    ADMIN_ID = os.environ.get('ADMIN_ID', '') # id of the admin user

    try:
        CHAT_TTL = os.environ.get('CHAT_TTL', 3600) # time it takes for a chat to unload from memory, in minutes
        CHAT_TTL = int(CHAT_TTL)

        MFA_TOKEN_EXPIRY = os.environ.get('MFA_TOKEN_EXPIRY', 2) # how long the admin panel token expires, in minutes
        MFA_TOKEN_EXPIRY = int(MFA_TOKEN_EXPIRY)

        JWT_EXPIRE_MINUTES = os.environ.get('JWT_EXPIRE_MINUTES', 180) # how long JWT tokens last, in minutes
        JWT_EXPIRE_MINUTES = int(JWT_EXPIRE_MINUTES)
    except ValueError:
        CHAT_TTL = 3600
        MFA_TOKEN_EXPIRY = 2
        JWT_EXPIRE_MINUTES = 180

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