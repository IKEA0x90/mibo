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

class ToolStickerRequest(ToolRequest):
    def __init__(self, key_emoji: str, **kwargs):
        super().__init__('tool_sticker_request', key_emoji=key_emoji, **kwargs)
        
class ToolPropertyChangeRequest(ToolRequest):
    def __init__(self, property_name: str, value, **kwargs):
        super().__init__('tool_property_change_request', property_name=property_name, value=value, **kwargs)

class ToolMemorizeKeyInformationRequest(ToolRequest):
    def __init__(self, key: str, information: str, **kwargs):
        super().__init__('tool_memorize_key_information_request', key=key, information=information, **kwargs)

class ToolImageResponse(event.Event):
    def __init__(self, image, **kwargs):
        super().__init__('tool_image_response', image=image, **kwargs)

class ToolPollResponse(event.Event):
    def __init__(self, poll, **kwargs):
        super().__init__('tool_poll_response', poll=poll, **kwargs)

class ToolStickerResponse(event.Event):
    def __init__(self, sticker, **kwargs):
        super().__init__('tool_sticker_response', sticker=sticker, **kwargs)

class ToolPropertyChangeResponse(event.Event):
    def __init__(self, property_name: str, value, success: bool, **kwargs):
        super().__init__('tool_property_change_response', property_name=property_name, value=value, success=success, **kwargs)

class ToolMemorizeKeyInformationResponse(event.Event):
    def __init__(self, key: str, success: bool, **kwargs):
        super().__init__('tool_memorize_key_information_response', key=key, success=success, **kwargs)

