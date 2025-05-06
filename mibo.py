import asyncio
import os
import signal

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from services import sql, bus

class Mibo:
    def __init__(self, token: str, db_path: str = "env/mibo.db"):
        self.db = sql.Database(db_path)
        self.bus = bus.EventBus()
        self.chance = 100

        self.assistants = {} 

        self._prepare()
        self._launch(token)
        self.app = Application.builder().token(token).build()

        self._register_handlers()

    def _prepare(self):
        '''
        Prepare the bot by loading the database and setting up signal handlers.
        '''
        self.db.initialize()
        self.assistants = self.db.get_assistants()
        self._system_signals()    
    
    def _launch(self, token: str):
        '''
        Start the bot
        '''
        self.app = Application.builder().token(token).build()
        self._register_handlers()
        self._wakeup()

    def _register_handlers(self):
        '''
        Register telegram handlers for commands and messages.
        '''
        self.app.add_handler(CommandHandler("debug", self.debug))
        self.app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), self.TelegramEvents.handle_))

    def _system_signals(self):
        '''
        Register system signals to stop the bot gracefully.
        '''
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.stop_event.set)

    def _handle_direct_message(self, message, reply = None):
        '''
        This event handles direct messages to the bot,
        And messages mentioning to the bot in group chats - @itsmiibot
        Both of these are always replied to. 
        '''
        pass

    def _handle_replies(self, new_message, reply):
        '''
        This event handles replies to the bot in group chats.
        It does not matter if the bot is mentioned or not - replies are always answered.
        '''
        pass

    def _handle_conversation(self, message):
        '''
        This is the event for passive conversation.
        This has a self.chance of being added to the bus
        '''
        pass

    def _handle_exception(self, e):
        '''
        This event handles all exceptions that occur in the bot, in any of the services.
        '''
        pass

        
    def _change_chance(self, chance: int):
        '''
        Change the chance of group message response.
        '''
        self.chance = chance

    def _register_bus_handlers(self):
        '''
        Maps all events that the bot will listen to the bus 
        '''
        bus.register("direct_message", self._handle_ping)
        bus.register("group_reply", self._handle_ping)
        bus.register("group_ping", self._handle_ping)

    class TelegramEvents:
        '''
        This is a reference class for easy access to telegram events
        '''

        @staticmethod
        async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await bus.emit("command_start", update)

        @staticmethod
        async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await bus.emit("message_text", update)