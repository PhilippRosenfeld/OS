import pytest

from horus.session.auth import hash_password, verify_password
from horus.session.user import User, UserRegistry, UserRole
from horus.session.seed import seed_users


# --- hash_password / verify_password ---

def test_verify_password_accepts_the_correct_password():
    stored = hash_password("hunter2")
    assert verify_password("hunter2", stored) is True


def test_verify_password_rejects_a_wrong_password():
    stored = hash_password("hunter2")
    assert verify_password("wrong", stored) is False


def test_hash_password_uses_a_random_salt_by_default():
    """Same password, hashed twice, must produce different stored strings --
    otherwise identical passwords would be trivially recognizable/crackable
    via a precomputed table."""
    a = hash_password("hunter2")
    b = hash_password("hunter2")
    assert a != b
    assert verify_password("hunter2", a) is True
    assert verify_password("hunter2", b) is True


def test_hash_password_with_explicit_salt_is_deterministic():
    salt = b"fixed-salt-value"
    a = hash_password("hunter2", salt=salt)
    b = hash_password("hunter2", salt=salt)
    assert a == b


def test_hash_password_stores_salt_and_digest_as_hex_separated_by_colon():
    stored = hash_password("hunter2", salt=b"\x01\x02")
    salt_hex, _, digest_hex = stored.partition(":")
    assert salt_hex == "0102"
    assert all(c in "0123456789abcdef" for c in digest_hex)


def test_verify_password_is_case_and_whitespace_sensitive():
    stored = hash_password("Hunter2")
    assert verify_password("hunter2", stored) is False
    assert verify_password("Hunter2 ", stored) is False


# --- User / UserRegistry ---

def test_register_and_get_a_user():
    registry = UserRegistry()
    user = User(name="alice", role=UserRole.USER)
    registry.register(user)
    assert registry.get("alice") is user


def test_get_unknown_user_returns_none():
    registry = UserRegistry()
    assert registry.get("nobody") is None


def test_exists_reflects_registration():
    registry = UserRegistry()
    assert registry.exists("alice") is False
    registry.register(User(name="alice", role=UserRole.USER))
    assert registry.exists("alice") is True


def test_register_duplicate_name_raises():
    registry = UserRegistry()
    registry.register(User(name="alice", role=UserRole.USER))
    with pytest.raises(ValueError):
        registry.register(User(name="alice", role=UserRole.ADMIN))


def test_user_role_ordering_matches_privilege_level():
    """UserRole is an IntEnum specifically so relative privilege can be
    compared (e.g. 'is this role at least ADMIN?'); pin down the intended
    ordering so a future reshuffle of the enum doesn't silently invert it."""
    assert UserRole.USER < UserRole.ADMIN < UserRole.ROOT


# --- seed_users ---

def test_seed_users_registers_root_user1_and_user2():
    registry = UserRegistry()
    seed_users(registry)
    assert {registry.get("root").name, registry.get("user1").name, registry.get("user2").name} == {"root", "user1", "user2"}


def test_seed_users_root_has_no_password():
    registry = UserRegistry()
    seed_users(registry)
    assert registry.get("root").password_hash is None
    assert registry.get("root").role == UserRole.ROOT


def test_seed_users_user1_has_a_working_password():
    registry = UserRegistry()
    seed_users(registry)
    user1 = registry.get("user1")
    assert user1.password_hash is not None
    assert verify_password("password", user1.password_hash) is True
    assert verify_password("wrong", user1.password_hash) is False


def test_seed_users_user2_has_no_password():
    registry = UserRegistry()
    seed_users(registry)
    assert registry.get("user2").password_hash is None
