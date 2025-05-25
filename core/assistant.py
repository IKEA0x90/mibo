import openai
import datetime as dt
import random
import os
import asyncio

from copy import copy
from typing import List, Dict

from events import event_bus, conductor_events, assistant_events, system_events, tool_events, db_events
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

        self.messages = window.Window(chat_id, start_datetime, self.template, self.max_context_tokens, self.max_content_tokens)

        self._register()

    def _load(self):
        self.system_message = self.template.get('instructions', '')
        self.model = self.template.get('model', 'gpt-4.1')
        self.temperature = self.template.get('temperature', 0.95)
        
        self.tools = self.template.get('tools', [])

        self.custom_instructions = self.chat.custom_instructions
        self.chance = self.chat.chance
        self.max_context_tokens = self.chat.max_context_tokens
        self.max_content_tokens = self.chat.max_content_tokens
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
        self.bus.register(conductor_events.MessagePush, self._prepare)

    async def _prepare(self, event: conductor_events.MessagePush):
        '''
        Fill the window with old messages from the database, but do not trigger completions.
        '''
        msg = event.request
        if msg.chat_id != self.chat_id:
            return
        if self.ready:
            return
        
        mem_req = db_events.MemoryRequest(chat_id=self.chat_id)
        mem_resp = await self.bus.wait(mem_req, db_events.MemoryResponse)
        prev_msgs = sorted(mem_resp.messages, key=lambda m: m.datetime)

        tokens = 0
        for m in prev_msgs:
            mtoks = await m.tokens()
            if tokens + mtoks > self.max_context_tokens:
                break
            # Add directly to window, do not use add_message (which can trigger completions)
            await self.messages._insert_live_message(m)
            tokens += mtoks
        self.ready = True

    @staticmethod
    async def call_openai(sync_func, *args, **kwargs):
        '''
        Runs a synchronous OpenAI call in a thread pool, returns the result asynchronously.
        '''
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: sync_func(*args, **kwargs))
    
    @staticmethod
    async def call_openai_debug(sync_func, *args, **kwargs):
        '''
        Returns a string.
        '''
        return 'This is a debug response (stop wasting tokens!)'

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
        if message.ping:
            return True
        chance = random.randint(1, 100)
        if chance <= self.chance:
            return True
        return False

    async def _add_message(self, event: conductor_events.AssistantRequest):
        '''
        Process an assistant request event.
        Adds the message to the window.
        Triggers _trigger_completion().
        '''
        if event.chat_id != self.chat_id:
            return
        
        await self.messages.add_message(event.event_id, event.message, self.bus)
        run = await self._check_conditions(event.message)
        if run:
            typing = event.typing
            typing()

            ev = assistant_events.AssistantDirectRequest(message=event.message, event_id=event.event_id)
            await self.bus.emit(ev)

    async def _not_implemented(self, event_id: str, message: str):
        issue = system_events.ChatErrorEvent(self.chat_id, 'Whoops! An error occurred: {}', event_id=event_id)
        await self.bus.emit(issue)

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
        
        template = copy(self.assistant_object)

        user_messages: List[Dict] = await self.messages.transform_messages()
        messages: List[Dict] = []

        if self.custom_instructions:
            messages.append({
                'role': 'developer',
                'content': [{'type': 'text', 'text': self.custom_instructions}]
            })

        if (instr := template.get('instructions')):
            messages.append({
                'role': 'developer',
                'content': [{'type': 'text', 'text': instr}]
            })
        
        request = {'model': template['model']}
        for msg in user_messages:
            messages.append(msg)

        request['messages'] = messages

        try:
            response = await self.call_openai_debug()
            #response = await self.call_openai(self.client.chat.completions.create, **request, extra_body=self.extra_body)
            
            # Process the response
            response_message = response.choices[0].message
            
            # Check if there are tool calls
            if hasattr(response_message, 'tool_calls') and response_message.tool_calls:
                await self._not_implemented(event.event_id, 'Tools are not implemented yet.') 
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
                    response: wrapper.MessageWrapper = await self.bus.wait(tool_event, assistant_events.AssistantToolResponse)
                    # only some events require notification
                    if tool_name == tools.Tool.CREATE_IMAGE:
                        event = assistant_events.AssistantDirectRequest(response)
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
                    images = []
                if not message_text.strip() and not images:
                    return
                
                assistant_message = wrapper.MessageWrapper(
                    chat_id=self.chat_id,
                    message_id=str(response.id),
                    role='assistant',
                    user=tools.Tool.MIBO,
                    message=message_text,
                    ping=False,
                    datetime=dt.datetime.now(tz=dt.timezone.utc)
                )

                # Add images to content_list
                for img in images:
                    if 'image_url' in img:
                        assistant_message.add_content(wrapper.ImageWrapper(0, 0, '', img['image_url'].split(',')[-1]))

                # Add to window immediately (do not trigger completions)
                await self.messages.add_message(event.event_id, assistant_message, self.bus)

                # Emit the assistant response
                response_event = assistant_events.AssistantResponse(message=assistant_message, event_id=event.event_id)
                await self.bus.emit(response_event)

                # Emit MessagePush for bot message so it is added to db (but not completion)
                push_event = conductor_events.MessagePush(assistant_message, event_id=event.event_id)
                await self.bus.emit(push_event)

        except Exception as e:
            raise e
            #issue = system_events.ChatErrorEvent(self.chat_id, 'Whoops! An error occurred.', str(e), event_id=event.event_id)
            #await self.bus.emit(issue)

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

        elif interaction_type == tools.Tool.CREATE_POLL:
            ev = tool_events.ToolPollRequest(context=interaction_context, event_id=event.event_id)
            self.bus.emit(ev)

        elif interaction_type == tools.Tool.SEND_STICKER:
            ev = tool_events.ToolStickerRequest(context=interaction_context, event_id=event.event_id)
            self.bus.emit(ev)

        elif interaction_type == tools.Tool.CHANGE_PROPERTY:
            ev = tool_events.ToolPropertyChangeRequest(context=interaction_context, event_id=event.event_id)
            self.bus.emit(ev)

        elif interaction_type == tools.Tool.MEMORIZE_KEY_INFORMATION:
            ev = tool_events.ToolMemorizeKeyInformationRequest(context=interaction_context, event_id=event.event_id)
            self.bus.emit(ev)
        
        message = wrapper.MessageWrapper(
            chat_id=self.chat_id,
            role='assistant',
            user=tools.Tool.CAT_ASSISTANT,
            message=tool_args.get('message', ''),
            ping=True,
            datetime=dt.datetime.now(tz=dt.timezone.utc)
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