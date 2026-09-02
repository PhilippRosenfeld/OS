from dataclasses import dataclass
from enum import IntEnum


class UserRole(IntEnum):
    USER = 0
    ADMIN = 1
    ROOT = 2

@dataclass
class User:
    name: str
    role: UserRole
    password_hash: str | None = None #For later use

class UserRegistry:

    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    def register(self, user: User) -> None:
        if self.exists(user.name):
            raise ValueError(f"User '{user.name}' already exists")
        self._users[user.name] = user

    def get(self, name: str) -> User | None:
        return self._users.get(name)

    def exists(self, name: str) -> bool:
        return name in self._users
