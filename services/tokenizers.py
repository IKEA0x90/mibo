import tiktoken

class Tokenizer:
    def __init__(self):
        pass

    @staticmethod
    def gpt(text: str, model: str = 'gpt-4o'):
        encoding = tiktoken.encoding_for_model(model)
        tokens = len(encoding.encode(text))
        return tokens