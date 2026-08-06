import pytest

from horus.filesystem.backend.sqlite import SQLiteVFS
from horus.filesystem.backend.memory import InMemoryVFS
from horus.filesystem.node import NodeType
from horus.filesystem.path_utils import resolve_path


def make(tmp_path):
    return SQLiteVFS(tmp_path / "horus.db")


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


# --- SQLiteVFS: schema / root ---

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
