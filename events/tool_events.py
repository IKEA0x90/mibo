from typing import List
from events import event

class ToolRequest(event.Event):
    def __init__(self, description: str, **kwargs):
        super().__init__('tool_request', description=description, **kwargs)

class ToolImageRequest(ToolRequest):
    def __init__(self, context: str, **kwargs):
        super().__init__('tool_image_request', context=context, **kwargs)

class ToolPollRequest(ToolRequest):
    def __init__(self, question: str, options: List[str], multiple_choice: bool = False, **kwargs):
        super().__init__('tool_poll_request', question=question, options=options, multiple_choice=multiple_choice, **kwargs)

class ToolImageResponse(event.Event):
    def __init__(self, image, **kwargs):
        super().__init__('tool_image_response', image=image, **kwargs)

class ToolPollResponse(event.Event):
    def __init__(self, poll, **kwargs):
        super().__init__('tool_poll_response', poll=poll, **kwargs)

