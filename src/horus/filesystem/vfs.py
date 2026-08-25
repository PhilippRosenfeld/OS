from abc import ABC, abstractmethod
from horus.filesystem.node import Node


class VFS(ABC):
    """Abstract interface for the virtual filesystem. Commands and the
    Kernel only ever depend on this — never on a concrete backend."""

    @abstractmethod
    def resolve_path(self, cwd: str, path: str) -> str:
        """Resolve a possibly-relative path against cwd into an absolute,
        normalized path (handles '.', '..', '~', leading '/')."""
        pass

    @abstractmethod
    def list_dir(self, path: str, show_all: bool, recursive: bool) -> list[Node]:
        pass

    @abstractmethod
    def mkdir(self, path: str, user: str, hidden: bool = False, protected: bool = False) -> None:
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        pass

    @abstractmethod
    def write_file(self, path: str, content: str, user: str, protected: bool = False) -> None:
        pass

    @abstractmethod
    def read_file(self, path: str) -> str:
        pass
    
    @abstractmethod
    def remove(self, path: str,  user: str) -> None:
        pass

    @abstractmethod
    def chmod(self, path: str, user: str, mode: str) -> None:
        """Mode is a 3-digit octal string, e.g. '755'."""
        pass

    @abstractmethod
    def set_attributes(self, path: str, user: str, protected: bool = None,
                        hidden: bool = None, immutable: bool = None) -> None:
        """Updates only the attributes explicitly passed (non-None)."""
        pass
