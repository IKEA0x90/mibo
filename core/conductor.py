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
        Listens to mibo events on the bus and processes them into MessageWrappers.
        '''
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

            if not chat_id or not message_id:
                return
        
        except Exception as e:
            raise e
            #await self.bus.emit(system_events.ErrorEvent("Woah! Somehow, this telegram message can't be parsed.", e))

        try:
            user = user.username or user.first_name
            role = 'assistant' if user == self.username else 'user'

            message_text = message.text or ''
            entities = message.parse_entities(types=[
                'mention',
                'url'
            ])

            ping = False

            if chat.type == chat.PRIVATE:
                ping = True 

            if entities:
                for entity, value in entities:
                    entity = cast(MessageEntity, entity) # for type hinting

                    if entity.type == 'mention':
                        if entity.user and entity.user.username == self.username:
                            ping = True

                    elif entity.type == 'url':
                        # special url processing
                        pass

            reply_message = message.reply_to_message
            reply_id = reply_message.message_id if reply_message else None

            datetime: dt.datetime = message.date.astimezone(dt.timezone.utc)
            
            message_wrapper = wrapper.MessageWrapper(chat_id, message_id, role, user, message_text, ping, reply_id, datetime)

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

            await self.bus.emit(conductor_events.AssistantRequest(chat_id=chat_id, message=message_wrapper, event_id=event.event_id, typing=event.typing))

        except Exception as e:
            import traceback
            traceback.print_exc()
            raise e
            #await self.bus.emit(system_events.ChatErrorEvent(chat_id=chat_id, error="Something's wrong with passing the messages from telegram to you.", e=e, event_id=event.event_id))