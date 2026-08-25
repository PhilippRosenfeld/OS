from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class NodeType(Enum):
    FILE = "file"
    DIRECTORY = "directory"

@dataclass
class Node:
    name:str
    type: NodeType
    owner: str = "root"
    permissions: str ="rwxr-xr-x"
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    hidden: bool = False
    protected: bool = False #File only changeable by sudo
    immutable: bool = False #blocks all changes
    size: int = 0
    
    
class ProtectedFileError(Exception):
    """Raised when attempting to remove or modify a protected file or directory,
    or to create/remove an entry inside a protected directory without force=True."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)