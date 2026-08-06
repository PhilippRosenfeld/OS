import pytest

from horus.filesystem.backend.sqlite import SQLiteVFS
from horus.filesystem.backend.memory import InMemoryVFS
from horus.filesystem.node import NodeType, ProtectedFileError
from horus.filesystem.path_utils import resolve_path


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
    ("../../../..", "/home", "/"),  # '..' past root silently clamps
])
def test_resolve_path(path, cwd, expected):
    assert resolve_path(path, cwd) == expected


def test_resolve_path_requires_cwd():
    with pytest.raises(ValueError):
        resolve_path("foo", "")


def test_inmemory_and_sqlite_resolve_path_agree(tmp_path):
    """Both backends delegate to the same shared helper -- pin that down so a
    future edit to one doesn't silently diverge from the other."""
    mem = InMemoryVFS()
    sql = make(tmp_path)
    assert mem.resolve_path("../etc", "/home/root") == sql.resolve_path("../etc", "/home/root")


# --- InMemoryVFS: remove ---

def test_inmemory_remove_deletes_a_file():
    fs = InMemoryVFS()
    fs.mkdir("/home")
    fs.write_file("/home/f.txt", "x")
    fs.remove("/home/f.txt")
    assert fs.exists("/home/f.txt") is False


def test_inmemory_remove_non_empty_directory_raises():
    fs = InMemoryVFS()
    fs.mkdir("/home")
    fs.write_file("/home/f.txt", "x")
    with pytest.raises(OSError):
        fs.remove("/home")
    assert fs.exists("/home/f.txt") is True


# --- SQLiteVFS: schema / root ---

def test_opening_a_pre_protected_column_db_migrates_it(tmp_path):
    """Regression test: a save created before the 'protected' column existed must
    still open (and gain the column with sensible defaults) instead of crashing --
    a plain CREATE TABLE IF NOT EXISTS doesn't retrofit new columns onto an
    already-existing table."""
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

    fs = SQLiteVFS(db_path)  # must not raise despite the missing column
    assert fs.get_meta("/").protected is False
    fs.mkdir("/home", protected=True)  # writing to the new column must work too
    assert fs.get_meta("/home").protected is True


def test_root_exists_on_a_fresh_database(tmp_path):
    fs = make(tmp_path)
    assert fs.exists("/")


def test_is_empty_true_for_a_fresh_database(tmp_path):
    fs = make(tmp_path)
    assert fs.is_empty() is True


def test_is_empty_false_after_creating_something(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    assert fs.is_empty() is False


def test_reopening_the_same_db_file_does_not_reset_the_schema(tmp_path):
    """Opening an already-initialized db a second time must not raise or wipe
    the root -- CREATE TABLE IF NOT EXISTS / INSERT OR IGNORE must hold."""
    db_path = tmp_path / "horus.db"
    fs1 = SQLiteVFS(db_path)
    fs1.mkdir("/home")
    fs1.close()

    fs2 = SQLiteVFS(db_path)  # reopen
    assert fs2.exists("/home")
    fs2.close()


# --- mkdir / exists ---

def test_mkdir_creates_directory(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    assert fs.exists("/home")
    assert fs.get_meta("/home").type == NodeType.DIRECTORY


def test_mkdir_missing_parent_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.mkdir("/no/such/parent")


def test_mkdir_duplicate_raises(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    with pytest.raises(FileExistsError):
        fs.mkdir("/home")


def test_mkdir_hidden_flag(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.mkdir("/home/.secret", hidden=True)
    assert fs.get_meta("/home/.secret").hidden is True


def test_exists_false_for_unknown_path(tmp_path):
    fs = make(tmp_path)
    assert fs.exists("/nope") is False


# --- write_file / read_file ---

def test_write_then_read_file(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.write_file("/home/readme.txt", "hello")
    assert fs.read_file("/home/readme.txt") == "hello"


def test_write_file_missing_parent_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.write_file("/no/such/dir/file.txt", "x")


def test_write_file_overwrites_existing_content_and_size(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.write_file("/home/f.txt", "hello")
    fs.write_file("/home/f.txt", "hi")
    assert fs.read_file("/home/f.txt") == "hi"
    assert fs.get_meta("/home/f.txt").size == 2


def test_read_file_missing_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.read_file("/nope.txt")


def test_read_file_on_a_directory_raises(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    with pytest.raises(FileNotFoundError):
        fs.read_file("/home")


# --- list_dir ---

def test_list_dir_returns_children(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.mkdir("/home/root")
    fs.write_file("/home/a.txt", "x")
    names = {n.name for n in fs.list_dir("/home")}
    assert names == {"root", "a.txt"}


def test_list_dir_hides_hidden_entries_by_default(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.mkdir("/home/.secret", hidden=True)
    assert fs.list_dir("/home") == []
    assert len(fs.list_dir("/home", show_all=True)) == 1


def test_list_dir_recursive_flattens_subdirectories(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.mkdir("/home/root")
    fs.write_file("/home/root/f.txt", "x")
    names = {n.name for n in fs.list_dir("/home", recursive=True)}
    assert names == {"root", "f.txt"}


def test_list_dir_missing_path_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.list_dir("/nope")


def test_list_dir_on_a_file_raises(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.write_file("/home/f.txt", "x")
    with pytest.raises(NotADirectoryError):
        fs.list_dir("/home/f.txt")


# --- get_meta ---

def test_get_meta_missing_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.get_meta("/nope")


def test_get_meta_reflects_written_file(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.write_file("/home/f.txt", "hello")
    meta = fs.get_meta("/home/f.txt")
    assert meta.name == "f.txt"
    assert meta.type == NodeType.FILE
    assert meta.size == 5


def test_timestamps_are_stored_at_second_precision(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    meta = fs.get_meta("/home")
    assert meta.created_at.microsecond == 0
    assert meta.modified_at.microsecond == 0


# --- remove ---

def test_remove_deletes_a_file(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.write_file("/home/f.txt", "x")
    fs.remove("/home/f.txt")
    assert fs.exists("/home/f.txt") is False


def test_remove_deletes_an_empty_directory(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.remove("/home")
    assert fs.exists("/home") is False


def test_remove_non_empty_directory_raises(tmp_path):
    fs = make(tmp_path)
    fs.mkdir("/home")
    fs.write_file("/home/f.txt", "x")
    with pytest.raises(OSError):
        fs.remove("/home")
    assert fs.exists("/home/f.txt") is True  # nothing was deleted


def test_remove_missing_path_raises(tmp_path):
    fs = make(tmp_path)
    with pytest.raises(FileNotFoundError):
        fs.remove("/nope")


# --- protected nodes (both backends -- this is a VFS-interface contract) ---

def test_protected_file_cannot_be_overwritten_even_with_force(fs):
    """Protection on the target itself is never bypassed -- force only lifts the
    *parent's* restriction on creating/removing entries, never a node's own flag."""
    fs.mkdir("/home")
    fs.write_file("/home/f.txt", "original", protected=True)

    with pytest.raises(ProtectedFileError):
        fs.write_file("/home/f.txt", "changed", force=True)
    assert fs.read_file("/home/f.txt") == "original"


def test_write_file_protected_flag_only_applies_on_creation():
    """Rewriting an existing (unprotected) file must not silently protect it."""
    fs = InMemoryVFS()
    fs.mkdir("/home")
    fs.write_file("/home/f.txt", "original")
    fs.write_file("/home/f.txt", "changed", protected=True)  # protected= is ignored on update
    fs.write_file("/home/f.txt", "changed again")  # still not protected -> should just work
    assert fs.read_file("/home/f.txt") == "changed again"


def test_protected_directory_cannot_be_removed(fs):
    fs.mkdir("/home")
    fs.mkdir("/home/locked", protected=True)
    with pytest.raises(ProtectedFileError):
        fs.remove("/home/locked")
    assert fs.exists("/home/locked") is True


def test_protected_directory_cannot_be_removed_even_with_force(fs):
    fs.mkdir("/home")
    fs.mkdir("/home/locked", protected=True)
    with pytest.raises(ProtectedFileError):
        fs.remove("/home/locked", force=True)
    assert fs.exists("/home/locked") is True


def test_creating_a_file_inside_a_protected_directory_requires_force(fs):
    fs.mkdir("/home")
    fs.mkdir("/home/locked", protected=True)
    with pytest.raises(ProtectedFileError):
        fs.write_file("/home/locked/f.txt", "x")
    assert fs.exists("/home/locked/f.txt") is False

    fs.write_file("/home/locked/f.txt", "x", force=True)  # the special method
    assert fs.read_file("/home/locked/f.txt") == "x"


def test_creating_a_subdirectory_inside_a_protected_directory_requires_force(fs):
    fs.mkdir("/home")
    fs.mkdir("/home/locked", protected=True)
    with pytest.raises(ProtectedFileError):
        fs.mkdir("/home/locked/sub")
    assert fs.exists("/home/locked/sub") is False

    fs.mkdir("/home/locked/sub", force=True)
    assert fs.exists("/home/locked/sub") is True


def test_removing_a_file_inside_a_protected_directory_requires_force(fs):
    fs.mkdir("/home")
    fs.mkdir("/home/locked", protected=True)
    fs.write_file("/home/locked/f.txt", "x", force=True)

    with pytest.raises(ProtectedFileError):
        fs.remove("/home/locked/f.txt")
    assert fs.exists("/home/locked/f.txt") is True

    fs.remove("/home/locked/f.txt", force=True)
    assert fs.exists("/home/locked/f.txt") is False


def test_a_child_that_is_itself_protected_resists_force(fs):
    """force only bypasses the *parent's* protection over its children -- a child
    that is independently marked protected still can't be touched, even with force."""
    fs.mkdir("/home")
    fs.mkdir("/home/locked", protected=True)
    fs.mkdir("/home/locked/inner", protected=True, force=True)

    with pytest.raises(ProtectedFileError):
        fs.remove("/home/locked/inner", force=True)
    assert fs.exists("/home/locked/inner") is True


def test_unprotected_directory_does_not_require_force(fs):
    fs.mkdir("/home")  # not protected
    fs.write_file("/home/f.txt", "x")  # should just work, no force needed
    fs.remove("/home/f.txt")
    assert fs.exists("/home/f.txt") is False


# --- persistence across reconnects (the whole point of switching to SQLite) ---

def test_content_persists_across_reconnect(tmp_path):
    db_path = tmp_path / "horus.db"
    fs1 = SQLiteVFS(db_path)
    fs1.mkdir("/home")
    fs1.write_file("/home/readme.txt", "welcome")
    fs1.close()

    fs2 = SQLiteVFS(db_path)
    assert fs2.is_empty() is False
    assert fs2.read_file("/home/readme.txt") == "welcome"
