def seed_users(registry: UserRegistry) -> None:
    registry.register(User(name="root", role = UserRole.ROOT))
    registry.register(User(name="user1", role = UserRole.USER))
