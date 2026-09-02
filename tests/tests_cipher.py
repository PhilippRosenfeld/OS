import pytest

from horus.filesystem.cipher import WrongKeyError, decrypt_bytes, encrypt_bytes


@pytest.mark.parametrize("method", ["xor", "aes"])
def test_encrypt_then_decrypt_round_trips(method):
    stored = encrypt_bytes(b"hello world", "k", method=method)
    plaintext = decrypt_bytes(stored, "k", method=method)
    assert plaintext == b"hello world"


def test_encrypted_output_does_not_contain_the_plaintext():
    stored = encrypt_bytes(b"top secret", "k")
    assert b"top secret" not in stored.encode("ascii")


def test_stored_string_is_prefixed_with_the_method():
    assert encrypt_bytes(b"x", "k", method="xor").startswith("xor:")
    assert encrypt_bytes(b"x", "k", method="aes").startswith("aes:")


def test_xor_and_aes_produce_different_ciphertext_for_the_same_input():
    xor_stored = encrypt_bytes(b"same data", "k", method="xor")
    aes_stored = encrypt_bytes(b"same data", "k", method="aes")
    assert xor_stored != aes_stored


def test_decrypt_with_wrong_key_raises():
    stored = encrypt_bytes(b"hello", "right-key")
    with pytest.raises(WrongKeyError):
        decrypt_bytes(stored, "wrong-key")


def test_decrypt_with_wrong_method_raises_even_with_the_right_key():
    """The method isn't read back from the stored data -- it has to be
    supplied again, exactly like the key, so guessing it wrong fails the
    same way a wrong key does."""
    stored = encrypt_bytes(b"hello", "k", method="xor")
    with pytest.raises(WrongKeyError):
        decrypt_bytes(stored, "k", method="aes")


def test_decrypt_of_non_encrypted_data_raises():
    with pytest.raises(ValueError):
        decrypt_bytes("just some text with no colon-separated method", "k")


def test_encrypt_with_empty_key_raises():
    with pytest.raises(ValueError):
        encrypt_bytes(b"data", "", method="xor")


def test_decrypt_with_empty_key_raises():
    stored = encrypt_bytes(b"data", "k")
    with pytest.raises(ValueError):
        decrypt_bytes(stored, "")


def test_unknown_method_raises():
    with pytest.raises(ValueError):
        encrypt_bytes(b"data", "k", method="rot13")


def test_encrypt_handles_data_longer_than_the_key():
    long_data = b"x" * 1000
    stored = encrypt_bytes(long_data, "short", method="xor")
    plaintext = decrypt_bytes(stored, "short", method="xor")
    assert plaintext == long_data
