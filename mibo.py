import asyncio
import os
import signal
import openai

import datetime as dt
from telegram import Update, Chat, ChatMember
from telegram.ext import Application, CallbackContext, CommandHandler, MessageHandler, ChatMemberHandler, filters

from events import event_bus, mibo_events, system_events
from core import assistant, database, conductor, system_messages

class Mibo:
    def __init__(self, token: str, db_path: str = 'env'):
        self.token = token
        self.start_datetime = dt.datetime.now(dt.timezone.utc).timestamp()

        self.db = database.Database(db_path)
        self.bus = event_bus.EventBus()
        self.conductor = conductor.Conductor(self.bus)

        self.system_chat: str = os.environ['SYSTEM_CHAT']
        self.key = os.environ['OPENAI_API_KEY']
        
        self.client = None
        self.assistants = {} 
        self.app = None

        self._prepare(token)

    def _prepare(self):
        '''
        Prepare the bot by loading the database, getting the openai client, and setting up signal handlers.
        '''
        self.db.initialize()
        
        self.client = openai.AsyncOpenAI(api_key=self.key)
        temporary_client = openai.OpenAI(api_key=self.key)

        template_assistant: str = os.environ['MIBO_ID']
        self.template_assistant = temporary_client.beta.assistants.retrieve(template_assistant)

        self.assistants = assistant.initialize_assistants(self.db, self.client, self.bus, self.template_assistant, self.start_datetime)
        
        self._register_handlers()
        self.app = Application.builder().token(self.token).build()

        self._system_signals()

    async def run(self, token: str):
        '''
        Start the bot
        '''
        await self.app.initialize()
        polling_task = asyncio.create_task(self.app.start())

        # block until _system_signals() flips the flag
        await self.stop_event.wait()

        # kill Mibo (oh no!)
        await self._shutdown(polling_task)

    def _register_handlers(self):
        '''
        Register telegram handlers for commands and messages.
        '''
        self.app.add_handler(CommandHandler('debug', self._debug))
        self.app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), self._handle_message))
        self.app.add_handler(ChatMemberHandler(self._welcome, ChatMemberHandler.MY_CHAT_MEMBER))

    def _system_signals(self):
        '''
        Register system signals to stop the bot gracefully.
        '''
        loop = asyncio.get_running_loop()

        def _on_signal(sig: signal.Signals) -> None:
            # Flip the in‑memory flag so `await self.stop_event.wait()` in the main task unblocks.
            self.stop_event.set()

            # inform the rest of the application through the EventBus.
            asyncio.create_task(
                self.bus.emit(system_events.ShutdownEvent(sig=sig))
            )

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_signal, sig)
        
    async def _shutdown(self, polling_task: asyncio.Task):
        print('Shutting down...')

        # stop Telegram
        await self.app.stop()
        await self.app.shutdown()

        # close services
        await self.bus.close()
        await self.db.close()

        # polling task cancellation
        polling_task.cancel()
        await asyncio.gather(polling_task, return_exceptions=True)

        print('Shutdown complete.')

    async def _handle_message(self, update: Update, context: CallbackContext):
        '''
        Handles direct and group messages to the bot,
        messages mentioning to the bot in group chats - @itsmiibot,
        messages that are replies to the bot (set ping to True and reply_to to the original message),
        and messages that ping the bot and that are replies to other messages. 

        This just sends the message to the bus.
        The message is processed by the conductor, 
        which creates a MessageWrapper and sends it to the rest of services.
        '''
        event = self.bus.emit(mibo_events.MiboMessage(update, start_datetime=self.start_datetime))

    async def _system_message(self, chat_id, system_message):
        '''
        Forces the bot to send a message to a chat, possibly appending a system message to the prompt.
        '''
        event = self.bus.emit(mibo_events.MiboSystemMessage(chat_id, system_message, start_datetime=self.start_datetime))

    async def _debug(self, update: Update, context: CallbackContext):
        '''
        Sends a debug message.
        '''
        await context.bot.send_message(update.effective_chat.id, 'Debug OK')

    async def _welcome(self, update: Update, context: CallbackContext):
        '''
        Sends a message to the group when the bot joins.
        '''
        chat = update.effective_chat
        old_status = update.my_chat_member.old_chat_member.status
        new_status = update.my_chat_member.new_chat_member.status

        if chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
            if old_status == ChatMember.ADMINISTRATOR:
                pass

async def main() -> None:
    token = os.environ['mibo']
    bot = Mibo(token)
    await bot.run()

if __name__ == '__main__':
    asyncio.run(main())