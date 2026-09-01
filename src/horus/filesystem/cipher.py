"""Ciphers backing the in-game 'encrypt'/'decrypt' commands (cmd_fs.py).

These are NOT real cryptography: 'aes' is a keyed keystream derived from the
key via SHA-256, not the actual AES algorithm. That's intentional -- this is
a terminal-hacking gameplay mechanic (encrypted files need the right key to
read again), not a security boundary, and implementing real AES by hand
would be worse than not having it. If real encryption is ever needed here,
reach for a proper library (e.g. `cryptography`) instead of extending this.
"""

import base64
import hashlib

_MAGIC = b"HORUS1:"  # prefixed to the plaintext before encrypting; its absence
                      # after decrypting means the key and/or method was wrong,
                      # since our keystream ciphers can't otherwise detect that


class WrongKeyError(Exception):
    """Raised by decrypt_bytes() when the given key and/or method doesn't
    match the ones the data was encrypted with (or the data is corrupted).
    Decrypting requires both the right key AND the right method -- there is
    no way to recover one from the other."""


def _xor(data: bytes, keystream: bytes) -> bytes:
    return bytes(b ^ keystream[i % len(keystream)] for i, b in enumerate(data))


def _sha_keystream(length: int, key: bytes) -> bytes:
    """Expands `key` into a `length`-byte keystream by chaining SHA-256
    blocks (key || counter), so 'aes' produces different-looking ciphertext
    from plain repeating-key 'xor'."""
    stream = bytearray()
    counter = 0
    while len(stream) < length:
        stream.extend(hashlib.sha256(key + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(stream[:length])


def _keystream(length: int, key: bytes, method: str) -> bytes:
    if method == "xor":
        return (key * (length // len(key) + 1))[:length]
    if method == "aes":
        return _sha_keystream(length, key)
    raise ValueError(f"unknown encryption method: '{method}'")


def encrypt_bytes(data: bytes, key: str, method: str = "xor") -> str:
    """Returns a self-describing 'method:base64_ciphertext' string, safe to
    store in a text-only content column."""
    if not key:
        raise ValueError("key must not be empty")

    payload = _MAGIC + data
    cipher = _xor(payload, _keystream(len(payload), key.encode("utf-8"), method))
    return f"{method}:{base64.b64encode(cipher).decode('ascii')}"


def decrypt_bytes(stored: str, key: str, method: str = "xor") -> bytes:
    """Reverses encrypt_bytes(). `method` must be the exact one the data was
    encrypted with -- it is NOT read back from `stored`, so guessing it wrong
    fails exactly like guessing the key wrong. Raises WrongKeyError if `key`
    and/or `method` don't recover the magic marker."""
    if not key:
        raise ValueError("key must not be empty")

    _, sep, b64 = stored.partition(":")
    if not sep:
        raise ValueError("not encrypted data")

    cipher = base64.b64decode(b64)
    payload = _xor(cipher, _keystream(len(cipher), key.encode("utf-8"), method))

    if not payload.startswith(_MAGIC):
        raise WrongKeyError("wrong key or method")
    return payload[len(_MAGIC):]
