from horus.filesystem.backend.memory import InMemoryVFS
from horus.shell.completion import complete_path

ROOT = "root"


def make_fs():
    fs = InMemoryVFS()
    fs.mkdir("/home", user=ROOT)
    fs.mkdir("/home/root", user=ROOT)
    fs.write_file("/home/root/poem.txt", "..", user=ROOT)
    fs.write_file("/home/root/readme.txt", "..", user=ROOT)
    fs.mkdir("/etc", user=ROOT)
    fs.write_file("/etc/passwd", "..", user=ROOT)
    return fs


def test_completes_within_cwd_when_prefix_has_no_slash():
    fs = make_fs()
    assert complete_path(fs, "/home/root", "p") == ["poem.txt"]


def test_completes_a_named_relative_subdirectory():
    """The reported bug: 'cat root/p' from /home must look inside /home/root,
    not match bare names in /home against the full 'root/p' string."""
    fs = make_fs()
    assert complete_path(fs, "/home", "root/p") == ["root/poem.txt"]


def test_candidates_carry_the_directory_prefix_along():
    fs = make_fs()
    candidates = complete_path(fs, "/home", "root/")
    assert set(candidates) == {"root/poem.txt", "root/readme.txt"}


def test_completes_an_absolute_path():
    fs = make_fs()
    assert complete_path(fs, "/home/root", "/etc/pa") == ["/etc/passwd"]


def test_empty_prefix_lists_everything_in_cwd():
    fs = make_fs()
    assert set(complete_path(fs, "/home/root", "")) == {"poem.txt", "readme.txt"}


def test_no_matches_returns_empty_list():
    fs = make_fs()
    assert complete_path(fs, "/home/root", "zzz") == []


def test_nonexistent_directory_returns_empty_list_instead_of_raising():
    fs = make_fs()
    assert complete_path(fs, "/home/root", "nosuchdir/p") == []


def test_multi_level_relative_path():
    fs = make_fs()
    fs.mkdir("/home/root/sub", user=ROOT)
    fs.write_file("/home/root/sub/deep.txt", "..", user=ROOT)
    assert complete_path(fs, "/home", "root/sub/d") == ["root/sub/deep.txt"]
