"""cd, mkdir, rm, chmod and ls -R -- run against SQLiteVFS, the backend the
game itself uses."""
import pytest

from horus.display.screen_buffer import ScreenBuffer
from horus.filesystem.backend.memory import InMemoryVFS
from horus.filesystem.backend.sqlite import SQLiteVFS
from horus.kernel.commands.cmd_fs import cd, chmod, ls, mkdir, rm
from horus.session.context import Context


def full_text(buffer):
    return "\n".join("".join(buffer.get_cell(c, r).char for c in range(buffer.cols)) for r in range(buffer.rows))


@pytest.fixture
def shell(tmp_path):
    """A root shell in /home on a fresh SQLiteVFS; returns (run, ctx, fs).
    run(command, *argv) clears the screen first, so it returns only what
    that one call printed."""
    fs = SQLiteVFS(tmp_path / "horus.db")
    fs.mkdir("/home", user="root")
    buffer = ScreenBuffer(100, 20)
    ctx = Context(session_id="s", user="root", cwd="/home", fs=fs, screen=buffer)

    def run(cmd, *argv):
        buffer.clear()
        buffer.cursor_row, buffer.cursor_col = 0, 0
        cmd(ctx, list(argv))
        return full_text(buffer)

    yield run, ctx, fs
    fs.close()


def as_user(ctx, user):
    ctx.user = ctx.effective_user = user


# --- cd ---

def test_cd_into_a_subdirectory_relative_and_absolute(shell):
    run, ctx, fs = shell
    fs.mkdir("/home/docs", user="root")
    run(cd, "docs")
    assert ctx.cwd == "/home/docs"
    run(cd, "..")
    assert ctx.cwd == "/home"
    run(cd, "/home/docs")
    assert ctx.cwd == "/home/docs"


def test_cd_to_a_missing_path_or_a_file_is_refused(shell):
    run, ctx, fs = shell
    fs.write_file("/home/notes.txt", "hi", user="root")
    assert "cd: No such file or directory: nope" in run(cd, "nope")
    assert "cd: No such file or directory: notes.txt" in run(cd, "notes.txt")
    assert ctx.cwd == "/home"


def test_cd_without_a_path_stays_put(shell):
    run, ctx, _ = shell
    run(cd)
    assert ctx.cwd == "/home"


# --- mkdir ---

def test_mkdir_creates_a_directory(shell):
    run, _, fs = shell
    assert run(mkdir, "docs").strip() == ""
    assert fs.get_file_type("/home/docs") == ".dir"


@pytest.mark.parametrize("flag,attribute", [("-H", "hidden"), ("-p", "protected"), ("-i", "immutable")])
def test_mkdir_flags_set_the_attribute(shell, flag, attribute):
    run, _, fs = shell
    run(mkdir, flag, "docs")
    assert getattr(fs.get_meta("/home/docs"), attribute) is True


def test_mkdir_reports_an_existing_directory(shell):
    run, _, fs = shell
    fs.mkdir("/home/docs", user="root")
    assert "mkdir: cannot create directory 'docs': File exists" in run(mkdir, "docs")


def test_mkdir_reports_a_missing_parent(shell):
    run, _, fs = shell
    assert "mkdir: cannot create directory 'a/b'" in run(mkdir, "a/b")
    assert not fs.exists("/home/a/b")


def test_mkdir_inside_a_protected_directory_needs_root(shell):
    run, ctx, fs = shell
    fs.mkdir("/home/vault", user="root", protected=True)
    as_user(ctx, "user1")
    assert "mkdir: " in run(mkdir, "vault/x")
    assert not fs.exists("/home/vault/x")


@pytest.mark.xfail(strict=True, reason="bug: mkdir passes immutable= but InMemoryVFS.mkdir doesn't accept it")
def test_mkdir_works_on_the_in_memory_backend_too():
    fs = InMemoryVFS()
    fs.mkdir("/home", user="root")
    ctx = Context(session_id="s", user="root", cwd="/home", fs=fs, screen=ScreenBuffer(80, 5))
    mkdir(ctx, ["docs"])
    assert fs.exists("/home/docs")


# --- rm ---

def test_rm_removes_a_file_and_an_empty_directory(shell):
    run, _, fs = shell
    fs.write_file("/home/notes.txt", "hi", user="root")
    fs.mkdir("/home/empty", user="root")
    assert "Removed: notes.txt" in run(rm, "notes.txt")
    assert "Removed: empty" in run(rm, "empty")
    assert not fs.exists("/home/notes.txt") and not fs.exists("/home/empty")


def test_rm_reports_a_missing_file(shell):
    run, _, _ = shell
    assert "rm: cannot remove 'nope': No such file or directory" in run(rm, "nope")


def test_rm_of_someone_elses_file_is_denied(shell):
    run, ctx, fs = shell
    fs.write_file("/home/root.txt", "hi", user="root")
    as_user(ctx, "user1")
    assert "rm: cannot remove 'root.txt': Permission denied" in run(rm, "root.txt")
    assert fs.exists("/home/root.txt")


@pytest.mark.xfail(strict=True, reason="bug: rm doesn't catch OSError('Directory not empty')")
def test_rm_of_a_non_empty_directory_is_reported(shell):
    run, _, fs = shell
    fs.mkdir("/home/full", user="root")
    fs.write_file("/home/full/a.txt", "hi", user="root")
    assert "rm: cannot remove 'full'" in run(rm, "full")
    assert fs.exists("/home/full/a.txt")


# --- chmod ---

def test_chmod_sets_the_permissions(shell):
    run, _, fs = shell
    fs.write_file("/home/notes.txt", "hi", user="root")
    run(chmod, "640", "notes.txt")
    assert fs.get_meta("/home/notes.txt").permissions == "rw-r-----"


@pytest.mark.parametrize("mode", ["75", "7555", "789", "abc"])
def test_chmod_rejects_an_invalid_mode(shell, mode):
    run, _, fs = shell
    fs.write_file("/home/notes.txt", "hi", user="root")
    before = fs.get_meta("/home/notes.txt").permissions
    assert "chmod: invalid" in run(chmod, mode, "notes.txt")
    assert fs.get_meta("/home/notes.txt").permissions == before


def test_chmod_reports_a_missing_file(shell):
    run, _, _ = shell
    assert "chmod: cannot access 'nope': No such file or directory" in run(chmod, "755", "nope")


def test_chmod_of_someone_elses_file_is_not_permitted(shell):
    run, ctx, fs = shell
    fs.write_file("/home/root.txt", "hi", user="root")
    before = fs.get_meta("/home/root.txt").permissions
    as_user(ctx, "user1")
    assert "chmod: changing permissions of 'root.txt': Operation not permitted" in run(chmod, "777", "root.txt")
    assert fs.get_meta("/home/root.txt").permissions == before


# --- ls -R (tree) ---

def test_ls_tree_indents_subdirectories_and_marks_them(shell):
    run, _, fs = shell
    fs.mkdir("/home/a", user="root")
    fs.mkdir("/home/a/b", user="root")
    fs.write_file("/home/a/b/deep.txt", "hi", user="root")
    fs.write_file("/home/top.txt", "hi", user="root")
    lines = [line.rstrip() for line in run(ls, "-R").splitlines() if line.strip()]
    assert lines == ["a/", "  b/", "    deep.txt", "top.txt"]


def test_ls_tree_hides_hidden_entries_unless_all(shell):
    run, _, fs = shell
    fs.mkdir("/home/secret", user="root", hidden=True)
    assert "secret/" not in run(ls, "-R")
    assert "secret/" in run(ls, "-R", "-a")


def test_ls_in_a_deleted_directory_reports_it(shell):
    run, ctx, _ = shell
    ctx.cwd = "/home/gone"
    assert "ls: File not found" in run(ls)
