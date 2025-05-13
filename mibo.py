import asyncio
import os
import signal
import openai

from telegram import Update
from telegram.ext import Application, CallbackContext, CommandHandler, MessageHandler, ContextTypes, filters

from events import event_bus, mibo_events
from core import assistant, database, conductor

class Mibo:
    def __init__(self, token: str, db_path: str = 'env'):
        self.db = database.Database(db_path)
        self.bus = event_bus.EventBus()
        self.conductor = conductor.Conductor(self.bus)

        self.system_chat: str = os.environ['SYSTEM_CHAT']
        self.key = os.environ['OPENAI_API_KEY']
        
        self.client = None
        self.assistants = {} 

        self._prepare()
        self._launch(token)

    def _prepare(self):
        '''
        Prepare the bot by loading the database, getting the openai client, and setting up signal handlers.
        '''
        self.db.initialize()
        
        self.client = openai.AsyncOpenAI(api_key=self.key)
        temporary_client = openai.OpenAI(api_key=self.key)

        template_assistant: str = os.environ['MIBO_ID']
        self.template_assistant = temporary_client.beta.assistants.retrieve(template_assistant)

        self.assistants = assistant.intialize_assistants(self.db, self.client, self.bus, self.template_assistant)

        self._system_signals()
    
    def _launch(self, token: str):
        '''
        Start the bot
        '''
        self.app = Application.builder().token(token).build()
        self._register_handlers()

    def _register_handlers(self):
        '''
        Register telegram handlers for commands and messages.
        '''
        self.app.add_handler(CommandHandler("debug", self._debug))
        self.app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), self._handle_message))

    def _system_signals(self):
        '''
        Register system signals to stop the bot gracefully.
        '''
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop_event.set)

    async def _handle_message(self, update: Update, context: CallbackContext):
        '''
        Handles direct and group messages to the bot,
        messages mentioning to the bot in group chats - @itsmiibot,
        messages that are replies to the bot (set ping to True and reply_to to the original message),
        and messages that ping the bot and that are replies to other messages. 
        '''
        event = self.bus.emit(mibo_events.MiboMessage(update))

    async def _system_message(self, chat_id, system_message):
        '''
        Forces the bot to send a message to a chat, possibly appending a system message to the prompt.
        '''
        event = self.bus.emit(mibo_events.MiboSystemMessage(chat_id, system_message))

    async def _debug(self, update: Update, context: CallbackContext):
        '''
        Sends a debug message.
        '''
        await context.bot.send_message(update.effective_chat.id, "Debug OK")

    async def _welcome(self, update: Update, context: CallbackContext):
        '''
        Sends a message to the group when the bot joins.
        '''
        pass

    async def _join_alert(self, update: Update, context: CallbackContext):
        '''
        Sends a message to the group when the bot joins.
        '''
        pass
        
    async def _change_arg(self, update: Update, context: CallbackContext):
        '''
        Changes an argument.
        '''
        pass

    async def process_groupchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
        '''
        Reads telegram messages in group chats.
        '''

    async def process_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
        '''
        Reads telegram messages in dms.
        '''
        # call the handlers with parameters
        pass