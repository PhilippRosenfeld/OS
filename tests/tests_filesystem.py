import pytest

from horus.filesystem.backend.memory import InMemoryVFS
from horus.filesystem.backend.sqlite import SQLiteVFS
from horus.filesystem.cipher import WrongKeyError
from horus.filesystem.node import NodeType
from horus.filesystem.path_utils import resolve_path
from horus.filesystem.permissions import AccessDeniedError
from horus.session.user import UserRole

ROOT = "root"
ROOT_ROLE = UserRole.ROOT


def make(tmp_path):
    return SQLiteVFS(tmp_path / "horus.db")


@pytest.fixture(params=["memory", "sqlite"])
def fs(request, tmp_path):
    """Runs a test against both backends, since the protected-node contract is
    part of the VFS interface, not a SQLite-only concern."""
    if request.param == "sqlite":
        return SQLiteVFS(tmp_path / "horus.db")
    return InMemoryVFS()


# --- path_utils.resolve_path (shared by every backend) ---

@pytest.mark.parametrize("path,cwd,expected", [
    ("foo", "/home", "/home/foo"),
    ("/foo", "/home", "/foo"),
    ("..", "/home/root", "/home"),
    ("../../etc", "/home/root", "/etc"),
    ("", "/home", "/home"),
    (".", "/home", "/home"),
    ("../../../..", "/home", "/"),
])
def test_resolve_path(path, cwd, expected):
    assert resolve_path(path, cwd) == expected


def test_resolve_path_requires_cwd():
    with pytest.raises(ValueError):
        resolve_path("foo", "")


def test_inmemory_and_sqlite_resolve_path_agree(tmp_path):
    mem = InMemoryVFS()
    sql = make(tmp_path)
    assert mem.resolve_path("../etc", "/home/root") == sql.resolve_path("../etc", "/home/root")


# --- InMemoryVFS: remove ---

def test_inmemory_remove_deletes_a_file():
    fs = InMemoryVFS()
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "x", user=ROOT)
    fs.remove("/home/f.txt", user=ROOT)
    assert fs.exists("/home/f.txt") is False


def test_inmemory_remove_non_empty_directory_raises():
    fs = InMemoryVFS()
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "x", user=ROOT)
    with pytest.raises(OSError):
        fs.remove("/home", user=ROOT)
    assert fs.exists("/home/f.txt") is True


# --- SQLiteVFS: schema / root ---

def test_opening_a_pre_protected_column_db_migrates_it(tmp_path):
    import sqlite3
    db_path = tmp_path / "horus.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE nodes (
            path TEXT PRIMARY KEY,
            parent_path TEXT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            owner TEXT NOT NULL DEFAULT 'root',
            permissions TEXT NOT NULL DEFAULT 'rwxr-xr-x',
            created_at TEXT NOT NULL,
            modified_at TEXT NOT NULL,
            hidden INTEGER NOT NULL DEFAULT 0,
            size INTEGER NOT NULL DEFAULT 0,
            content TEXT
        )
    """)
    conn.execute(
        "INSERT INTO nodes (path, parent_path, name, type, owner, permissions, created_at, modified_at, hidden, size) "
        "VALUES ('/', NULL, '/', 'directory', 'root', 'rwxr-xr-x', '2020-01-01T00:00:00', '2020-01-01T00:00:00', 0, 0)"
    )
    conn.commit()
    conn.close()

    fs = SQLiteVFS(db_path)
    assert fs.get_meta("/").protected is False
    fs.mkdir("/home", user=ROOT, protected=True)
    assert fs.get_meta("/home").protected is True


def test_root_exists_on_a_fresh_database(tmp_path):
    fs = make(tmp_path)
    assert fs.exists("/")


def test_is_empty_true_for_a_fresh_database(tmp_path):
    fs = make(tmp_path)
    assert fs.is_empty() is True


def test_is_empty_false_after_creating_something(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    assert fs.is_empty() is False


def test_reopening_the_same_db_file_does_not_reset_the_schema(tmp_path):
    db_path = tmp_path / "horus.db"
    fs1 = SQLiteVFS(db_path)
    fs1.mkdir("/home", user=ROOT)
    fs1.close()

    fs2 = SQLiteVFS(db_path)
    assert fs2.exists("/home")
    fs2.close()


# --- mkdir / exists ---

def test_mkdir_creates_directory(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    assert fs.exists("/home")
    assert fs.get_meta("/home").type == NodeType.DIRECTORY


def test_mkdir_missing_parent_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.mkdir("/no/such/parent", user=ROOT)


def test_mkdir_duplicate_raises(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    with pytest.raises(FileExistsError):
        fs.mkdir("/home", user=ROOT)


def test_mkdir_hidden_flag(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.mkdir("/home/.secret", user=ROOT, hidden=True)
    assert fs.get_meta("/home/.secret").hidden is True


def test_exists_false_for_unknown_path(tmp_path):
    fs = make(tmp_path)
    assert fs.exists("/nope") is False


# --- write_file / read_file ---

def test_write_then_read_file(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/readme.txt", "hello", user=ROOT)
    assert fs.read_file("/home/readme.txt", user=ROOT) == "hello"


def test_write_file_missing_parent_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.write_file("/no/such/dir/file.txt", "x", user=ROOT)


def test_write_file_overwrites_existing_content_and_size(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "hello", user=ROOT)
    fs.write_file("/home/f.txt", "hi", user=ROOT)
    assert fs.read_file("/home/f.txt", user=ROOT) == "hi"
    assert fs.get_meta("/home/f.txt").size == 2


def test_read_file_missing_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.read_file("/nope.txt", user=ROOT)


def test_read_file_on_a_directory_raises(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    with pytest.raises(FileNotFoundError):
        fs.read_file("/home", user=ROOT)


# --- read_file permission checks ---

def test_read_file_denied_without_read_permission(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "eyes only", user=ROOT)
    fs.chmod("/home/secret.txt", mode="700", user=ROOT)  # owner-only, no read for others

    with pytest.raises(AccessDeniedError):
        fs.read_file("/home/secret.txt", user="user1")


def test_read_file_allowed_with_default_permissions(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/notes.txt", "hi", user=ROOT)  # default rwxr-xr-x: others can read
    assert fs.read_file("/home/notes.txt", user="user1") == "hi"


def test_read_file_owner_can_read_their_own_file_regardless_of_other_bits(fs):
    fs.mkdir("/home", user=ROOT)
    fs.chmod("/home", mode="777", user=ROOT)  # let user1 create things in here
    fs.mkdir("/home/user1", user="user1")
    fs.write_file("/home/user1/notes.txt", "mine", user="user1")
    fs.chmod("/home/user1/notes.txt", mode="700", user="user1")  # locks out everyone but the owner
    assert fs.read_file("/home/user1/notes.txt", user="user1") == "mine"


def test_root_can_always_read_a_file(fs):
    fs.mkdir("/home", user=ROOT)
    fs.chmod("/home", mode="777", user=ROOT)
    fs.mkdir("/home/user1", user="user1")
    fs.write_file("/home/user1/notes.txt", "mine", user="user1")
    fs.chmod("/home/user1/notes.txt", mode="700", user="user1")
    assert fs.read_file("/home/user1/notes.txt", user=ROOT) == "mine"


# --- list_dir ---

def test_list_dir_returns_children(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.mkdir("/home/root", user=ROOT)
    fs.write_file("/home/a.txt", "x", user=ROOT)
    names = {n.name for n in fs.list_dir("/home")}
    assert names == {"root", "a.txt"}


def test_list_dir_hides_hidden_entries_by_default(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.mkdir("/home/.secret", user=ROOT, hidden=True)
    assert fs.list_dir("/home") == []
    assert len(fs.list_dir("/home", show_all=True)) == 1


def test_list_dir_recursive_flattens_subdirectories(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.mkdir("/home/root", user=ROOT)
    fs.write_file("/home/root/f.txt", "x", user=ROOT)
    names = {n.name for n in fs.list_dir("/home", recursive=True)}
    assert names == {"root", "f.txt"}


def test_list_dir_missing_path_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.list_dir("/nope")


def test_list_dir_on_a_file_raises(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "x", user=ROOT)
    with pytest.raises(NotADirectoryError):
        fs.list_dir("/home/f.txt")


# --- get_meta ---

def test_get_meta_missing_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.get_meta("/nope")


def test_get_meta_reflects_written_file(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "hello", user=ROOT)
    meta = fs.get_meta("/home/f.txt")
    assert meta.name == "f.txt"
    assert meta.type == NodeType.FILE
    assert meta.size == 5


# --- get_file_type ---

def test_get_file_type_returns_extension_with_leading_dot(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/notes.txt", "hi", user=ROOT)
    assert fs.get_file_type("/home/notes.txt") == ".txt"


def test_get_file_type_returns_dot_dir_for_directories(fs):
    fs.mkdir("/home", user=ROOT)
    assert fs.get_file_type("/home") == ".dir"


def test_get_file_type_with_no_extension_returns_empty_string(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/README", "hi", user=ROOT)
    assert fs.get_file_type("/home/README") == ""


def test_get_file_type_uses_only_the_last_extension(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/archive.tar.gz", "hi", user=ROOT)
    assert fs.get_file_type("/home/archive.tar.gz") == ".gz"


def test_get_file_type_treats_a_leading_dot_as_no_extension(fs):
    """A dotfile like '.bashrc' isn't 'extension bashrc' -- matches
    pathlib.Path.suffix's own convention for leading-dot names."""
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/.bashrc", "hi", user=ROOT)
    assert fs.get_file_type("/home/.bashrc") == ""


def test_get_file_type_missing_path_raises(fs):
    with pytest.raises(FileNotFoundError):
        fs.get_file_type("/nope.txt")


# --- encrypt_file / decrypt_file ---

def test_encrypt_file_appends_crypt_extension_and_removes_old_path(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT)

    new_path = fs.encrypt_file("/home/secret.txt", user=ROOT, role=ROOT_ROLE, key="k")

    assert new_path == "/home/secret.txt.crypt"
    assert fs.exists("/home/secret.txt.crypt") is True
    assert fs.exists("/home/secret.txt") is False
    assert fs.get_file_type(new_path) == ".crypt"


def test_encrypted_content_is_not_the_plaintext(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT)
    new_path = fs.encrypt_file("/home/secret.txt", user=ROOT, role=ROOT_ROLE, key="k")
    assert "top secret" not in fs.read_file(new_path, user=ROOT)


def test_decrypt_file_restores_original_path_and_content(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT)
    new_path = fs.encrypt_file("/home/secret.txt", user=ROOT, role=ROOT_ROLE, key="k")

    restored_path = fs.decrypt_file(new_path, user=ROOT, role=ROOT_ROLE, key="k")

    assert restored_path == "/home/secret.txt"
    assert fs.exists("/home/secret.txt") is True
    assert fs.exists(new_path) is False
    assert fs.read_file("/home/secret.txt", user=ROOT) == "top secret"


def test_decrypt_file_with_aes_method_round_trips(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT)
    new_path = fs.encrypt_file("/home/secret.txt", user=ROOT, role=ROOT_ROLE, key="k", method="aes")

    restored_path = fs.decrypt_file(new_path, user=ROOT, role=ROOT_ROLE, key="k", method="aes")

    assert fs.read_file(restored_path, user=ROOT) == "top secret"


def test_decrypt_file_with_wrong_key_raises_and_leaves_file_untouched(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT)
    new_path = fs.encrypt_file("/home/secret.txt", user=ROOT, role=ROOT_ROLE, key="right")

    with pytest.raises(WrongKeyError):
        fs.decrypt_file(new_path, user=ROOT, role=ROOT_ROLE, key="wrong")
    assert fs.exists(new_path) is True  # still encrypted -- nothing was silently corrupted


def test_decrypt_file_with_wrong_method_raises_even_with_the_right_key(fs):
    """The method is a real part of the secret, not just a hint -- decrypting
    with the wrong one fails exactly like the wrong key would, since it's
    never read back from the stored data."""
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT)
    new_path = fs.encrypt_file("/home/secret.txt", user=ROOT, role=ROOT_ROLE, key="k", method="xor")

    with pytest.raises(WrongKeyError):
        fs.decrypt_file(new_path, user=ROOT, role=ROOT_ROLE, key="k", method="aes")
    assert fs.exists(new_path) is True  # still encrypted


def test_encrypt_file_on_missing_path_raises(fs):
    with pytest.raises(FileNotFoundError):
        fs.encrypt_file("/nope.txt", user=ROOT, role=ROOT_ROLE, key="k")


def test_encrypt_file_on_a_directory_raises(fs):
    fs.mkdir("/home", user=ROOT)
    with pytest.raises(FileNotFoundError):
        fs.encrypt_file("/home", user=ROOT, role=ROOT_ROLE, key="k")


def test_encrypt_file_already_encrypted_raises(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT)
    new_path = fs.encrypt_file("/home/secret.txt", user=ROOT, role=ROOT_ROLE, key="k")
    with pytest.raises(ValueError):
        fs.encrypt_file(new_path, user=ROOT, role=ROOT_ROLE, key="k")


def test_decrypt_file_on_a_non_encrypted_file_raises(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/plain.txt", "hi", user=ROOT)
    with pytest.raises(ValueError):
        fs.decrypt_file("/home/plain.txt", user=ROOT, role=ROOT_ROLE, key="k")


def test_encrypt_file_requires_write_permission(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT, protected=True)
    with pytest.raises(AccessDeniedError):
        fs.encrypt_file("/home/secret.txt", user="alice", role=UserRole.USER, key="k")


# --- encrypt_file / decrypt_file: protected/immutable use a role-based check,
# not the plain username-based one every other write path uses ---

def test_encrypt_file_on_a_protected_file_allows_admin_role(fs):
    """Unlike every other write path (rm, chmod, write_file, ...), which only
    ever allows the literal 'root' account on a protected node, encrypt/decrypt
    accept ADMIN or higher."""
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT, protected=True)
    new_path = fs.encrypt_file("/home/secret.txt", user="bob", role=UserRole.ADMIN, key="k")
    assert fs.exists(new_path) is True


def test_encrypt_file_on_a_protected_file_rejects_plain_user_role(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT, protected=True)
    with pytest.raises(AccessDeniedError):
        fs.encrypt_file("/home/secret.txt", user="bob", role=UserRole.USER, key="k")


def test_encrypt_file_on_an_immutable_file_requires_root_role(fs):
    """Unlike can_write() (used by every other write path), which blocks
    immutable files for everyone -- even root -- unless chattr clears the
    flag first, encrypt/decrypt let ROOT act on it directly."""
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT)
    fs.set_attributes("/home/secret.txt", user=ROOT, immutable=True)

    with pytest.raises(AccessDeniedError):
        fs.encrypt_file("/home/secret.txt", user="bob", role=UserRole.ADMIN, key="k")

    new_path = fs.encrypt_file("/home/secret.txt", user=ROOT, role=UserRole.ROOT, key="k")
    assert fs.exists(new_path) is True


def test_decrypt_file_on_an_immutable_encrypted_file_requires_root_role(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT)
    new_path = fs.encrypt_file("/home/secret.txt", user=ROOT, role=ROOT_ROLE, key="k")
    fs.set_attributes(new_path, user=ROOT, immutable=True)

    with pytest.raises(AccessDeniedError):
        fs.decrypt_file(new_path, user="bob", role=UserRole.ADMIN, key="k")

    restored_path = fs.decrypt_file(new_path, user=ROOT, role=UserRole.ROOT, key="k")
    assert fs.exists(restored_path) is True


def test_encrypt_file_on_a_plain_file_still_uses_permission_bits(fs):
    """Non-protected, non-immutable files fall back to the normal owner/other
    rwx bits -- role doesn't enter into it, same as can_write()."""
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/secret.txt", "top secret", user=ROOT)
    fs.chmod("/home/secret.txt", mode="600", user=ROOT)

    with pytest.raises(AccessDeniedError):
        fs.encrypt_file("/home/secret.txt", user="bob", role=UserRole.ADMIN, key="k")

    new_path = fs.encrypt_file("/home/secret.txt", user=ROOT, role=ROOT_ROLE, key="k")
    assert fs.exists(new_path) is True


def test_timestamps_are_stored_at_second_precision(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    meta = fs.get_meta("/home")
    assert meta.created_at.microsecond == 0
    assert meta.modified_at.microsecond == 0


# --- remove ---

def test_remove_deletes_a_file(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "x", user=ROOT)
    fs.remove("/home/f.txt", user=ROOT)
    assert fs.exists("/home/f.txt") is False


def test_remove_deletes_an_empty_directory(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.remove("/home", user=ROOT)
    assert fs.exists("/home") is False


def test_remove_non_empty_directory_raises(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "x", user=ROOT)
    with pytest.raises(OSError):
        fs.remove("/home", user=ROOT)
    assert fs.exists("/home/f.txt") is True


def test_remove_missing_path_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.remove("/nope", user=ROOT)


# --- protected nodes (both backends -- VFS-interface contract) ---
# New model: 'protected' means only root may write/remove the node --
# not even its owner. root can always bypass it directly; there is no
# separate 'force' escape hatch anymore.

def test_protected_file_cannot_be_written_by_non_root(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "original", user=ROOT, protected=True)

    with pytest.raises(AccessDeniedError):
        fs.write_file("/home/f.txt", "changed", user="user1")
    assert fs.read_file("/home/f.txt", user=ROOT) == "original"


def test_protected_file_can_still_be_written_by_root(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "original", user=ROOT, protected=True)

    fs.write_file("/home/f.txt", "changed", user=ROOT)
    assert fs.read_file("/home/f.txt", user=ROOT) == "changed"


def test_write_file_protected_flag_only_applies_on_creation():
    """Rewriting an existing (unprotected) file must not silently protect it."""
    fs = InMemoryVFS()
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "original", user=ROOT)
    fs.write_file("/home/f.txt", "changed", user=ROOT, protected=True)  # ignored on update
    fs.write_file("/home/f.txt", "changed again", user=ROOT)  # still not protected -> should work
    assert fs.read_file("/home/f.txt", user=ROOT) == "changed again"


def test_protected_directory_cannot_be_removed_by_non_root(fs):
    fs.mkdir("/home", user=ROOT)
    fs.mkdir("/home/locked", user=ROOT, protected=True)
    with pytest.raises(AccessDeniedError):
        fs.remove("/home/locked", user="user1")
    assert fs.exists("/home/locked") is True


def test_protected_directory_can_be_removed_by_root(fs):
    fs.mkdir("/home", user=ROOT)
    fs.mkdir("/home/locked", user=ROOT, protected=True)
    fs.remove("/home/locked", user=ROOT)
    assert fs.exists("/home/locked") is False


def test_non_owner_cannot_write_into_a_directory_without_write_permission(fs):
    """Baseline (non-protected) permission check: a directory owned by root
    with default 'rwxr-xr-x' permissions only grants write to root/owner."""
    fs.mkdir("/home", user=ROOT)
    with pytest.raises(AccessDeniedError):
        fs.write_file("/home/f.txt", "x", user="user1")
    assert fs.exists("/home/f.txt") is False


def test_root_can_always_write_into_an_unprotected_directory(fs):
    fs.mkdir("/home", user=ROOT)
    fs.write_file("/home/f.txt", "x", user=ROOT)
    assert fs.read_file("/home/f.txt", user=ROOT) == "x"


def test_removing_a_file_inside_a_protected_directory_by_non_root_raises(fs):
    fs.mkdir("/home", user=ROOT)
    fs.mkdir("/home/locked", user=ROOT, protected=True)
    fs.write_file("/home/locked/f.txt", "x", user=ROOT)

    with pytest.raises(AccessDeniedError):
        fs.remove("/home/locked/f.txt", user="user1")
    assert fs.exists("/home/locked/f.txt") is True

    fs.remove("/home/locked/f.txt", user=ROOT)
    assert fs.exists("/home/locked/f.txt") is False


def test_a_protected_child_inside_a_protected_directory_still_requires_root(fs):
    fs.mkdir("/home", user=ROOT)
    fs.mkdir("/home/locked", user=ROOT, protected=True)
    fs.mkdir("/home/locked/inner", user=ROOT, protected=True)

    with pytest.raises(AccessDeniedError):
        fs.remove("/home/locked/inner", user="user1")
    assert fs.exists("/home/locked/inner") is True

    fs.remove("/home/locked/inner", user=ROOT)
    assert fs.exists("/home/locked/inner") is False


# --- persistence across reconnects (the whole point of switching to SQLite) ---

def test_content_persists_across_reconnect(tmp_path):
    db_path = tmp_path / "horus.db"
    fs1 = SQLiteVFS(db_path)
    fs1.mkdir("/home", user=ROOT)
    fs1.write_file("/home/readme.txt", "welcome", user=ROOT)
    fs1.close()

    fs2 = SQLiteVFS(db_path)
    assert fs2.is_empty() is False
    assert fs2.read_file("/home/readme.txt", user=ROOT) == "welcome"  # not just "something survived"
    assert fs2.get_meta("/home").type == NodeType.DIRECTORY
    fs2.close()


# --- seed_minimal / disk-sourced text files ---

def test_seed_minimal_reads_readme_content_from_disk():
    """readme.txt's content is authored as a real file under VFS_SEED_DIR,
    not a Python string literal -- this pins down that the seed step actually
    reads it rather than silently falling back to something else."""
    from horus.filesystem.seed import seed_minimal
    from horus.paths import VFS_SEED_DIR

    fs = InMemoryVFS()
    seed_minimal(fs)

    expected = (VFS_SEED_DIR / "readme.txt").read_text(encoding="utf-8")
    assert fs.read_file("/home/root/readme.txt", user=ROOT) == expected
    assert expected.strip() != ""  # sanity: the seed file itself isn't empty