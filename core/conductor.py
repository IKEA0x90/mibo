import sys
import datetime as dt

from typing import cast
from telegram import Update, Message, MessageEntity
from telegram.ext import CallbackContext

from events import event_bus, conductor_events, db_events, system_events, mibo_events
from core import wrapper
from services import tools

class Conductor:
    '''
    A layer between telegram and the services.
    Captures the raw event, parses it into a MessageWrapper, and adds it back to the bus.
    '''
    def __init__(self, bus):
        self.bus: event_bus.EventBus = bus
        self.username: str = tools.Tool.MIBO
        self._register()

    def _register(self):
        self.bus.register(mibo_events.MiboMessage, self._capture_message)

    async def _capture_message(self, event: mibo_events.MiboMessage):
        '''
        Listens to mibo events and processes them into MessageWrappers.
        ''' 
        system_message = hasattr(event, 'system')

        try:
            update: Update = event.update
            start_datetime: dt.datetime = event.start_datetime
            context: CallbackContext = event.context

            chat = update.effective_chat
            message: Message = update.message
            user = update.message.from_user
            
            if not chat or not message or not user:
                return

            chat_id = chat.id
            message_id = message.message_id
            chat_name = chat.effective_name or ''

            if not chat_id or not message_id:
                return
        
        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error="Woah! Somehow, this telegram message can't be parsed.", e=e, tb=tb, event_id=event.event_id))

        try:
            user = user.username or user.first_name
            if system_message:
                role = 'developer'
            else:
                role = 'assistant' if user == self.username else 'user'

            message_text = message.text or ''
            if not message_text:
                return
            
            entities = message.parse_entities(types=[
                'mention',
                'url'
            ])

            ping = False

            if chat.type == chat.PRIVATE or system_message:
                ping = True 

            if entities:
                for entity, value in entities.items():
                    entity = cast(MessageEntity, entity) # for type hinting

                    if entity.type == 'mention':
                        if value.startswith('@') and value[1:] == tools.Tool.MIBO_PING:
                            ping = True

                    elif entity.type == 'url':
                        # special url processing
                        pass
            
            reply_message = message.reply_to_message

            reply_id = reply_message.message_id if reply_message else None

            if reply_id and (reply_message.from_user.id == context.bot.id):
                ping = True

            if f'{tools.Tool.MIBO}' in message_text.lower() or f'{tools.Tool.MIBO_RU}' in message_text.lower():
                ping = True
                
            datetime: dt.datetime = message.date.astimezone(dt.timezone.utc)
            
            message_wrapper = wrapper.MessageWrapper(chat_id, message_id, role, user, message_text, ping, reply_id, datetime, chat_name=chat_name)

            request = conductor_events.ImageDownloadRequest(update=update, context=context)
            response = await self.bus.wait(request, db_events.ImageResponse, 30)

            if response and response.images:
                for image in response.images:
                    message_wrapper.add_content(image)

            push_request = conductor_events.MessagePush(message_wrapper, event_id=event.event_id)
            chat_response = await self.bus.wait(push_request, db_events.NewChatAck)
            chat_wrapper = chat_response.chat

            push_request = conductor_events.NewChatPush(chat_wrapper, event_id=event.event_id)
            await self.bus.wait(push_request, mibo_events.AssistantCreated)

            await self.bus.emit(conductor_events.AssistantRequest(chat_id=chat_id, message=message_wrapper, event_id=event.event_id, typing=event.typing, system=system_message))

        except Exception as e:
            _, _, tb = sys.exc_info()
            await self.bus.emit(system_events.ErrorEvent(error="Something's wrong with passing the messages from telegram to you.", e=e, tb=tb, event_id=event.event_id, chat_id=chat_id))