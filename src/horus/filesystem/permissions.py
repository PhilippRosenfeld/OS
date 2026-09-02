from horus.filesystem.node import Node
from horus.session.user import UserRole

class AccessDeniedError(Exception):
    def __init__(self, path: str, action: str):
        self.path = path
        self.action = action
        super().__init__(f"permission denied: cannot {action} '{path}'")


def can_write(node: Node, user: str) -> bool:
    if node.immutable:
        return False
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

def can_change_metadata(node: Node, user: str) -> bool:
    if node.protected:
        return user == "root"
    return user == "root" or node.owner == user

def require_write(node: Node, user: str, path: str) -> None:
    if not can_write(node, user):
        raise AccessDeniedError(path, "write to")

def can_write_encrypted(node: Node, user: str, role: UserRole) -> bool:
    """Like can_write(), but for encrypt/decrypt specifically: immutable
    requires ROOT directly (no chattr-then-modify two-step needed -- root
    can act on it right away), and protected only requires ADMIN or higher,
    not literally being the 'root' account. Plain (unflagged) files still
    fall back to the normal owner/other permission bits, same as can_write().

    This is intentionally separate from can_write() rather than changing it --
    every other write path (rm, chmod, write_file, mkdir, ...) keeps the
    existing name-based rules unchanged."""
    if node.immutable:
        return role >= UserRole.ROOT
    if node.protected:
        return role >= UserRole.ADMIN
    if user == "root":
        return True
    if node.owner == user:
        return "w" in node.permissions[0:3] #owner bits
    return "w" in node.permissions[6:9] #other bits

def require_write_encrypted(node: Node, user: str, role: UserRole, path: str) -> None:
    if not can_write_encrypted(node, user, role):
        raise AccessDeniedError(path, "write to")

def require_read(node: Node, user: str, path: str) -> None:
    if not can_read(node, user):
        raise AccessDeniedError(path, "read")

def require_metadata_change(node: Node, user: str, path: str) -> None:
    if not can_change_metadata(node, user):
        raise AccessDeniedError(path, "change attributes of")

def octal_to_permissions(mode: str) -> str:
    """Converts a 3-digit octal mode string ('754') into the 9-char
    rwx representation stored on Node.permissions ('rwxr-xr--')."""
    if len(mode) != 3 or not mode.isdigit():
        raise ValueError(f"invalid mode: '{mode}' (expected 3 octal digits, e.g. '755')")

    def digit_to_rwx(d: str) -> str:
        n = int(d)
        if not (0 <= n <= 7):
            raise ValueError(f"invalid octal digit: '{d}'")
        return ("r" if n & 4 else "-") + ("w" if n & 2 else "-") + ("x" if n & 1 else "-")

    return "".join(digit_to_rwx(d) for d in mode)