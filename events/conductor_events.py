from typing import Dict
from events import event
from core import window
from services import prompt_enum

class CompletionRequest(event.Event):
    def __init__(self, wdw: window.Window, request: Dict, prompts: Dict[prompt_enum.PromptEnum, str], special_fields: Dict, **kwargs):
        super().__init__('completion_request', wdw, **kwargs)
