_PROMPT_ENUM_REGISTRY = {}


class PromptEnum:
    def __new__(cls, id: str):
        # PromptEnum instances are never actually created, init returns class. 
        # access prompt dictionaries via class.
        if cls is PromptEnum:
            subclass = _PROMPT_ENUM_REGISTRY.get(id)
            if subclass:
                return subclass
        return super().__new__(cls)

    def __init__(self, id: str):
        self.event_id: str = id or 'base'

    def __str__(self):
        return self.event_id
        
    @classmethod
    def get_id(cls):
        for id_str, registered_cls in _PROMPT_ENUM_REGISTRY.items():
            if registered_cls == cls:
                return id_str
        return cls.__name__.lower().replace('prompt', '')

    @classmethod
    def register(cls, id: str):
        def decorator(subclass):
            _PROMPT_ENUM_REGISTRY[id] = subclass
            return subclass
        return decorator

@PromptEnum.register('base')
class BasePrompt(PromptEnum):
    def __init__(self):
        super().__init__('base')

@PromptEnum.register('welcome')
class WelcomePrompt(PromptEnum):
    def __init__(self):
        super().__init__('welcome')

@PromptEnum.register('start')
class StartPrompt(PromptEnum):
    def __init__(self):
        super().__init__('start')