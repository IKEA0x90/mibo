class PromptEnum:
    def __init__(self, id: str):
        self.event_id: str = id or 'base'

    def __str__(self):
        return self.event_id
    
class BasePrompt(PromptEnum):
    def __init__(self):
        super().__init__('base')

class WelcomePrompt(PromptEnum):
    def __init__(self):
        super().__init__('welcome')

class StartPrompt(PromptEnum):
    def __init__(self):
        super().__init__('start')