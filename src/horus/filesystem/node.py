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
    permisions: str ="rwxr-xr-x"
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    hidden: bool = False
    size: int = 0