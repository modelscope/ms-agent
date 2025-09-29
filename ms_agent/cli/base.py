from abc import ABC, abstractmethod
from argparse import ArgumentParser


class CLICommand(ABC):
    """The base class for CLI command classes.

    Derive from this class if there is a new command line tool.
    """

    @staticmethod
    @abstractmethod
    def define_args(parsers: ArgumentParser):
        raise NotImplementedError()

    @abstractmethod
    def execute(self):
        raise NotImplementedError()