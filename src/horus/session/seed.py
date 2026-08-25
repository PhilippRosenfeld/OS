from horus.session.auth import hash_password
from horus.session.user import UserRegistry, User, UserRole

def seed_users(registry: UserRegistry) -> None:
    registry.register(User(name="root", role = UserRole.ROOT))
    registry.register(User(name="user1", role = UserRole.USER, password_hash=hash_password("password")))
    registry.register(User(name="user2", role = UserRole.USER,))
