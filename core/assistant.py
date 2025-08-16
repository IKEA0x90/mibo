import openai
import datetime as dt
import random
import sys
import asyncio
import aiohttp

from copy import copy
from typing import List, Dict
from io import BytesIO
from PIL import Image

from events import event_bus, conductor_events, assistant_events, system_events, db_events, event
from core import ref, window, wrapper
from services import variables

class Assistant:
    def __init__(self, clients: List[openai.OpenAI], local_clients: List[openai.OpenAI], bus: event_bus.EventBus, refferrer: ref.Ref, start_datetime: dt.datetime, **kwargs):

        self.clients: List[openai.OpenAI] = clients
        self.local_clients: List[openai.OpenAI] = local_clients

        self.bus: event_bus.EventBus = bus
        self.ref: ref.Ref = refferrer
        self.start_datetime: dt.datetime = start_datetime

        self._register()

    def _register(self):
        self.bus.register(conductor_events.CompletionRequest, self._trigger_completion)

    @staticmethod
    async def call_openai(sync_func, *args, **kwargs):
        '''
        Runs a synchronous OpenAI call in a thread pool, returns the result asynchronously.
        '''
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: sync_func(*args, **kwargs))

    async def _trigger_completion(self, event: conductor_events.CompletionRequest):
        '''
        Trigger a chat completion and return the response message. 
        '''
        wdw: window.Window = event.wdw

        user_messages: List[Dict] = await wdw.transform_messages()
        messages: List[Dict] = []

        if self.custom_instructions:
            messages.append({
                'role': 'system',
                'content': [{'type': 'text', 'text': self.custom_instructions}]
            })

        if self.local_client and self.disable_think:
            messages.append({
                'role': 'system',
                'content': [{'type': 'text', 'text': self.no_think}]
            })

        if (instr := assistant_template.get('instructions')):
            messages.append({
                'role': 'system',
                'content': [{'type': 'text', 'text': instr}]
            })
        
        request = {'model': assistant_template['model']}
        for msg in user_messages:
            messages.append(msg)

        request['messages'] = messages

        try:
            if self.local_client:
                response = await self.call_openai(self.local_client.chat.completions.create, **request, extra_body=self.extra_body)
            else:
                response = await self.call_openai(self.client.chat.completions.create, **request, extra_body=self.extra_body)

            # Process the response
            response_message = response.choices[0].message
            
            # Check if there are tool calls
            if hasattr(response_message, 'tool_calls') and response_message.tool_calls:
                
                issue = system_events.ErrorEvent(error=f'Required functionality not implemented: {message}', e=NotImplementedError(message), tb=None, event_id=event.event_id, chat_id=self.chat_id)
                await self.bus.emit(issue)

                for tool_call in response_message.tool_calls:
                    if tool_call.type != "function_call":
                        continue
                    tool_name = tool_call.function.name
                    tool_args = tool_call.function.arguments
                    tool_event = assistant_events.AssistantToolRequest(
                        chat_id=self.chat_id,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        event_id=event.event_id
                    )
                    tool_response: wrapper.Wrapper = await self.bus.wait(tool_event, assistant_events.AssistantToolResponse)
                    # only some events require notification
                    if tool_name == variables.Variables.CREATE_IMAGE:
                        event = assistant_events.AssistantDirectRequest(tool_response)
                        await self.bus.emit(event)

            else:
                # For chat completions, content may be a list of blocks or a string
                content = response_message.content

                if isinstance(content, list):
                    # Concatenate all text blocks for message text, collect images for content_list
                    message_text = "".join([block.get('text', '') for block in content if block.get('type') == 'text'])
                    images = [block for block in content if block.get('type') == 'image_url']

                else:
                    message_text = content or ''
                    images = [] # if it's not a list, no images

                if not message_text.strip() and not images:
                    return
                
                # Replace random stuff that I don't like and is easier to change here rather than in the prompt
                message_text = variables.Variables.replacers(message_text)
                
                if self.local_client:
                    message_text = message_text.split(f'{self.think_end}', 1)[1]
                    message_text = message_text.strip()

                wrapper_list = []

                assistant_message = wrapper.MessageWrapper(
                    id=str(response.id), chat_id=self.chat_id, 
                    role='assistant', user=variables.Variables.MIBO,
                    message=message_text, ping=False,
                    datetime=dt.datetime.now(tz=dt.timezone.utc)
                )
                wrapper_list.append(assistant_message)

                # Add images to content_list
                for img in images:
                    if 'image_url' in img:
                        incomplete_wrapper = wrapper.ImageWrapper(id=str(response.id), chat_id=self.chat_id, x=0, y=0, role='assistant', user=variables.Variables.MIBO)
                        image = await self._download_image_url(img['image_url'], incomplete_wrapper=incomplete_wrapper, parent_event=event)
                        wrapper_list.append(image)

                # Add to window (do not trigger completions)
                for w in wrapper_list:
                    await self.messages.add_message(event.event_id, w, self.bus)

                # Emit the assistant response
                response_event = assistant_events.AssistantResponse(messages=wrapper_list, event_id=event.event_id)
                await self.bus.emit(response_event)

                # Emit WrapperPush for bot message so it is added to db (but not completion)
                push_event = conductor_events.WrapperPush(wrapper_list, chat_id=self.chat_id, event_id=event.event_id)
                await self.bus.emit(push_event)

        except Exception as e:
            _, _, tb = sys.exc_info()
            issue = system_events.ErrorEvent(error='Whoops! An unexpected error occurred.', e=e, tb=tb, event_id=event.event_id, chat_id=self.chat_id)
            await self.bus.emit(issue)

    async def _download_image_url(self, image_url: str, incomplete_wrapper: wrapper.ImageWrapper, parent_event: event.Event) -> wrapper.ImageWrapper:
        '''
        Downloads an image from a URL.
        Returns None if the download fails.
        '''
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=30) as response:

                    if response.status == 200:
                        image_bytes: bytes = await response.read()
                        incomplete_wrapper.image_bytes = image_bytes

                        def sync_process(img_bytes):
                            with Image.open(BytesIO(img_bytes)) as img:
                                width, height = img.size
                            return width, height

                        width, height = await asyncio.to_thread(sync_process, image_bytes)
                        incomplete_wrapper.x = width
                        incomplete_wrapper.y = height

                        return incomplete_wrapper

                    else:
                        issue = system_events.ErrorEvent(error='Error downloading an image.', e=None, tb=None, event_id=parent_event.event_id, chat_id=self.chat_id)
                        await self.bus.emit(issue)
                    
        except Exception as e:
            _, _, tb = sys.exc_info()
            issue = system_events.ErrorEvent(error='Error downloading an image.', e=e, tb=tb, event_id=parent_event.event_id, chat_id=self.chat_id)
            await self.bus.emit(issue)

class CatAssistant(Assistant):
    def __init__(self, chat_id, client, bus, templates, start_datetime, chat, assistant_type):
        super().__init__(f'system_{chat_id}', client, bus, templates, start_datetime, chat, assistant_type=assistant_type)

        self.outer_id = chat_id

        self._configure_events()

    def _configure_events(self):

        self.bus.unregister(conductor_events.AssistantRequest, self._add_message)
        self.bus.unregister(assistant_events.AssistantDirectRequest, self._trigger_completion)
        
        if self.assistant_type == variables.Variables.CAT_ASSISTANT:
            self.bus.register(assistant_events.AssistantToolRequest, self._tool_response)

        elif self.assistant_type in [variables.Variables.IMAGE_ASSISTANT, variables.Variables.POLL_ASSISTANT, variables.Variables.PROPERTY_ASSISTANT, variables.Variables.MEMORY_ASSISTANT]:
            self.bus.register(variables.Variables.get_event(self.assistant_type), self._tool_response)

    async def _tool_response(self, event: assistant_events.AssistantToolRequest):
        '''
        Listens for a tool request. 
        Asks the Cat Assistant to use a tool.
        Returns a short notification.
        '''
        if (event.chat_id != self.outer_id):
            return
        
        tool_name = event.tool_name
        tool_args = event.tool_args

        if tool_name != variables.Variables.CAT_ASSISTANT:
            return
        
        interaction_type = tool_args.get('interaction_type', None)
        interaction_context = tool_args.get('interaction_context', None)

        if not interaction_type or not interaction_context:
            return
        
        if interaction_type == variables.Variables.CREATE_IMAGE:
            ev = tool_events.VariablesImageRequest(context=interaction_context, event_id=event.event_id)
            self.bus.emit(ev)
        
        message = wrapper.MessageWrapper(
            id=None,
            chat_id=self.chat_id,
            message=tool_args.get('message', ''),
            ping=True,
            datetime=dt.datetime.now(tz=dt.timezone.utc),
            role='assistant',
            user=variables.Variables.CAT_ASSISTANT,
        )

        await self.messages.override(message)
        event = assistant_events.AssistantDirectRequest(message=message, event_id=event.event_id)
        await self.bus.emit(event)

    async def _use_tool(self, event: tool_events.VariablesRequest):
        '''
        Processes a tool request.
        '''
        if event.chat_id != self.outer_id:
            return
        
        if event.tool_name == variables.Variables.CAT_ASSISTANT:
            return
        
        if event.tool_name == variables.Variables.CREATE_IMAGE:
            prompt = ''
            image = await variables.Variables.create_image(prompt)