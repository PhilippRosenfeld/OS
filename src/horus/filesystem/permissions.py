from horus.filesystem.node import Node

class AccessDeniedError(Exception):
    def __init__(self, path: str, action: str):
        self.path = path
        self.action = action
        super().__init__(f"permission denied: cannot {action} '{path}'")


def can_write(node: Node, user: str) -> bool:
    if node.protected:
        return user == "root"
    if user == "root":
        return True
    if node.owner == user:
        return "w" in node.permissions[0:3] #owner bits
    return "w" in node.permissions[6:9] #other bits

def can_read(node: Node, user: str) -> bool:
    if user == "root":
        return True
    if node.owner == user:
        return "r" in node.permissions[0:3] #owner bits
    return "r" in node.permissions[6:9] #other bits

def require_write(node: Node, user: str, path: str) -> None:
    if not can_write(node, user):
        raise AccessDeniedError(path, "write to")

def require_read(node: Node, user: str, path: str) -> None:
    if not can_read(node, user):
        raise AccessDeniedError(path, "read")