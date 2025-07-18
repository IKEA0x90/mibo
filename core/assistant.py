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

from events import event_bus, conductor_events, assistant_events, system_events, tool_events, db_events, event
from core import database, window, wrapper
from services import tools

def initialize_assistants(db: database.Database, client: openai.OpenAI, bus: event_bus.EventBus, templates: Dict[str, Dict[str, str]], start_datetime: dt.datetime):
    '''
    Creates a dictionary of assistants for each chat in the database.
    '''
    assistants = {}

    chats = db.get_all_chats()
    chat: wrapper.ChatWrapper
    for chat in chats:
        chat_id = chat.chat_id
        assistants[chat_id] = Assistant(chat_id, client, bus, templates, start_datetime, chat, tools.Tool.MIBO)

    return assistants

class Assistant:
    def __init__(self, chat_id: str, client: openai.OpenAI, bus: event_bus.EventBus, templates: Dict[str, Dict[str, str]], 
                 start_datetime: dt.datetime, chat: wrapper.ChatWrapper, assistant_type: str = tools.Tool.MIBO):
        
        self.chat_id: str = chat_id
        self.client: openai.OpenAI = client
        self.bus: event_bus.EventBus = bus
        self.system_message: str = ''
        self.template: dict = templates.get('template', {})
        self.chat: wrapper.ChatWrapper = chat
        self.assistant_type: str = assistant_type
        self.start_datetime: dt.datetime = start_datetime

        # mibo only has the cat assistant
        if assistant_type == tools.Tool.MIBO:
            self.cat_assistant: CatAssistant = CatAssistant(chat_id, client, bus, templates, start_datetime, chat, tools.Tool.CAT_ASSISTANT)

        # cat assistant has the other assistants
        if assistant_type == tools.Tool.CAT_ASSISTANT:
            image_template = templates.get('image_template', {})
            poll_template = templates.get('poll_template', {})
            property_template = templates.get('property_template', {})
            memory_template = templates.get('memory_template', {})

            self.image_assistant: CatAssistant = CatAssistant(chat_id, client, bus, {'template': image_template}, start_datetime, chat, tools.Tool.IMAGE_ASSISTANT)
            self.poll_assistant: CatAssistant = CatAssistant(chat_id, client, bus, {'template': poll_template}, start_datetime, chat, tools.Tool.POLL_ASSISTANT)
            self.property_assistant: CatAssistant = CatAssistant(chat_id, client, bus, {'template': property_template}, start_datetime, chat, tools.Tool.PROPERTY_ASSISTANT)
            self.memory_assistant: CatAssistant = CatAssistant(chat_id, client, bus, {'template': memory_template}, start_datetime, chat, tools.Tool.MEMORY_ASSISTANT)

        self.death_timer = -1
        self.last_reply = -1
        self.ready = False

        self._load()

        self.messages = window.Window(chat_id, start_datetime, self.template, self.max_tokens)

        self._register()

    def _load(self):
        self.system_message = self.template.get('instructions', '')
        self.model = self.template.get('model', 'gpt-4.1')
        self.temperature = self.template.get('temperature', 0.95)
        
        self.tools = self.template.get('tools', [])

        self.custom_instructions = self.chat.custom_instructions
        self.chance = self.chat.chance
        self.max_tokens = self.chat.max_tokens
        self.max_response_tokens = self.chat.max_response_tokens

        self.frequency_penalty = self.chat.frequency_penalty
        self.presence_penalty = self.chat.presence_penalty

        self.assistant_object = {
            'model': self.model,
            'temperature': self.temperature,
            'max_output_tokens': self.max_response_tokens,
            'tools': self.tools,
            'instructions': self.system_message,
            'store': False,
            'tool_choice': 'auto',
            'truncation': 'auto',
        }

        self.extra_body = {
            'frequency_penalty': self.frequency_penalty,
            'presence_penalty': self.presence_penalty,
        }

    def _register(self):
        self.bus.register(conductor_events.AssistantRequest, self._add_message)
        self.bus.register(assistant_events.AssistantDirectRequest, self._trigger_completion)
        self.bus.register(conductor_events.WrapperPush, self._prepare)

    async def _prepare(self, event: conductor_events.WrapperPush):
        '''
        Prepare the window without triggering completions.
        '''
        if event.chat_id != self.chat_id or self.ready:
            return

        memory_request = db_events.MemoryRequest(chat_id=self.chat_id)
        memory_response = await self.bus.wait(memory_request, db_events.MemoryResponse)

        message: wrapper.Wrapper = None

        for message in memory_response.messages:
            if message.datetime < self.start_datetime:
                # backlog – include for context, no completion later
                await self.messages._insert_live_message(message)
                continue

            # live messages that arrived before the window was ready
            if not self.messages.contains(message):
                await self.messages._insert_live_message(message)

        self.ready = True

    @staticmethod
    async def call_openai(sync_func, *args, **kwargs):
        '''
        Runs a synchronous OpenAI call in a thread pool, returns the result asynchronously.
        '''
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: sync_func(*args, **kwargs))

    async def _check_conditions(self, message: wrapper.MessageWrapper) -> bool:
        '''
        First, checks if the window is ready.
        If not, return False. Othewise:
        If a message is a ping, a reply is guaranteed - return True.
        Otherwise, self.chance % chance to reply.
        When a reply happens, call _reply().
        '''
        if not self.messages.ready:
            return False

        if isinstance(message, wrapper.MessageWrapper):
            if message.ping:
                return True
            chance = random.randint(1, 100)
            if chance <= self.chance:
                return True
            return False
        
        #TODO no way to detect if a photo has a ping - link text to photo
        if isinstance(message, wrapper.ImageWrapper):
            return True

    async def _add_message(self, event: conductor_events.AssistantRequest):
        '''
        Process an assistant request event.
        Adds the message to the window.
        Triggers _trigger_completion().
        '''
        for message in event.messages:
            if event.chat_id != self.chat_id:
                return

            await self.messages.add_message(event.event_id, message, self.bus)
            run = await self._check_conditions(message)
            if run:
                typing = event.typing
                typing()

                ev = assistant_events.AssistantDirectRequest(message=message, event_id=event.event_id, system=event.system)
                await self.bus.emit(ev)

    async def _trigger_completion(self, event: assistant_events.AssistantDirectRequest):
        '''
        Makes a json request from self.window.transform_messages()
        Checks if messages requires a reply.
        If so, make a copy of self.assistant_object and add the message to it.
        Then, call openai with the json request.
        If the response contains tool calls, create a ToolRequest and emit it.
        Otherwise, create a message wrapper from the response and emit an assistant response.
        '''
        message = event.message
        if message.chat_id != self.chat_id:
            return
        
        if not self.messages.ready:
            return
        
        assistant_template = copy(self.assistant_object)

        user_messages: List[Dict] = await self.messages.transform_messages()
        messages: List[Dict] = []

        if self.custom_instructions:
            messages.append({
                'role': 'developer',
                'content': [{'type': 'text', 'text': self.custom_instructions}]
            })

        if (instr := assistant_template.get('instructions')):
            messages.append({
                'role': 'developer',
                'content': [{'type': 'text', 'text': instr}]
            })
        
        request = {'model': assistant_template['model']}
        for msg in user_messages:
            messages.append(msg)

        request['messages'] = messages

        try:
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
                    if tool_name == tools.Tool.CREATE_IMAGE:
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
                message_text = tools.Tool.replacers(message_text)
                
                wrapper_list = []

                assistant_message = wrapper.MessageWrapper(
                    id=str(response.id), chat_id=self.chat_id, 
                    role='assistant', user=tools.Tool.MIBO,
                    message=message_text, ping=False,
                    datetime=dt.datetime.now(tz=dt.timezone.utc)
                )
                wrapper_list.append(assistant_message)

                # Add images to content_list
                for img in images:
                    if 'image_url' in img:
                        incomplete_wrapper = wrapper.ImageWrapper(id=str(response.id), chat_id=self.chat_id, x=0, y=0, role='assistant', user=tools.Tool.MIBO)
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
        
        if self.assistant_type == tools.Tool.CAT_ASSISTANT:
            self.bus.register(assistant_events.AssistantToolRequest, self._tool_response)

        elif self.assistant_type in [tools.Tool.IMAGE_ASSISTANT, tools.Tool.POLL_ASSISTANT, tools.Tool.PROPERTY_ASSISTANT, tools.Tool.MEMORY_ASSISTANT]:
            self.bus.register(tools.Tool.get_event(self.assistant_type), self._tool_response)

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

        if tool_name != tools.Tool.CAT_ASSISTANT:
            return
        
        interaction_type = tool_args.get('interaction_type', None)
        interaction_context = tool_args.get('interaction_context', None)

        if not interaction_type or not interaction_context:
            return
        
        if interaction_type == tools.Tool.CREATE_IMAGE:
            ev = tool_events.ToolImageRequest(context=interaction_context, event_id=event.event_id)
            self.bus.emit(ev)
        
        message = wrapper.MessageWrapper(
            id=None,
            chat_id=self.chat_id,
            message=tool_args.get('message', ''),
            ping=True,
            datetime=dt.datetime.now(tz=dt.timezone.utc),
            role='assistant',
            user=tools.Tool.CAT_ASSISTANT,
        )

        await self.messages.override(message)
        event = assistant_events.AssistantDirectRequest(message=message, event_id=event.event_id)
        await self.bus.emit(event)

    async def _use_tool(self, event: tool_events.ToolRequest):
        '''
        Processes a tool request.
        '''
        if event.chat_id != self.outer_id:
            return
        
        if event.tool_name == tools.Tool.CAT_ASSISTANT:
            return
        
        if event.tool_name == tools.Tool.CREATE_IMAGE:
            prompt = ''
            image = await tools.Tool.create_image(prompt)