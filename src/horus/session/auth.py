import hashlib
import os

def hash_password(password: str, salt: bytes | None = None) -> str:
    """Returns 'salt_hex:digest_hex', suitable for storing in User.password_hash."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return f"{salt.hex()}:{digest.hex()}"

def verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split(":")
    salt = bytes.fromhex(salt_hex)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return candidate.hex() == digest_hex