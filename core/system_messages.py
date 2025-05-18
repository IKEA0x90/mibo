class SystemMessages:
    '''
    A collection of system messages used by mibo.
    '''
    @staticmethod
    @property
    def debug():
        return f'Your next message must contain the word "debug".'