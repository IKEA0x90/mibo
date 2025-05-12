import os
import asyncio

from typing import cast
from telegram import Update, MessageEntity

from events import event_bus, conductor_events, db_events, system_events
from core import wrapper

class Conductor:
    '''
    A layer between telegram and the services.
    Captures the raw event, parses it into a MessageWrapper, and adds it back to the bus.
    '''
    def __init__(self, bus):
        self.bus: event_bus.EventBus = bus
        self.username: str = os.environ['mibo_username']

    async def _capture_message(self, update: Update):
        '''
        Listens to mibo events on the bus and processes them into MessageWrappers.
        '''
        try:
            chat = update.effective_chat
            message = update.message
            user = update.message.from_user
            
            if not chat or not message or not user:
                return

            chat_id = chat.id
            message_id = message.message_id

            if not chat_id or not message_id:
                return
        
        except Exception as e:
            raise system_events.ErrorEvent('Message cannot be parsed..', e)

        try:
            user = user.username or user.first_name
            role = 'assistant' if user == self.username else 'user'

            message_text = message.text or ''
            entities = message.parse_entities(types=[
                'mention',
                'url'
            ])

            ping = False

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
            
            message_wrapper = wrapper.MessageWrapper(chat_id, message_id, role, user, message_text, ping, reply_id)

            request = conductor_events.ImageDownloadRequest(message=message)
            response = db_events.ImageResponse(image_path='')
            response = await self.bus.wait(request, response, 30)

            if response and response.response:
                for image_path in response.response:
                    content = wrapper.ImageWrapper(image_path)
                    message_wrapper.add_content(content)
            
            self.bus.emit(conductor_events.AssistantCall(message_wrapper))

        except Exception as e:
            self.bus.emit(system_events.ChatErrorEvent(chat_id=chat_id, error='An unexpted error occurred.', e=e))