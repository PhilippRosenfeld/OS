import argparse

class CommandArgumentParser(argparse.ArgumentParser):

    def exit(self, status: int = 0, message: str| None = None) -> None:
        raise CommandParseError(message or "", self.format_help())

    def error(self, message: str) -> None:
        raise CommandParseError(message, self.format_usage())



class CommandParseError(Exception):

    def __init__(self, message: str, usage : str) -> None:
        self.message = message
        self.usage = usage
        super().__init__(message)