from horus.filesystem.vfs import VFS
from horus.paths import VFS_SEED_DIR

# Plain-text content authored as real .txt files on disk (under VFS_SEED_DIR)
# instead of Python string literals, so longer content is easier to write and
# edit. Each entry is (path relative to VFS_SEED_DIR, destination VFS path) --
# add more here to seed additional files; the destination's parent directory
# must already exist by the time _seed_text_files() runs.
_TEXT_FILE_SEEDS: list[tuple[str, str]] = [
    ("readme.txt", "/system/root/readme.txt"),
    ("poem.txt", "/system/root/poems/poem.txt"),
    ("solstice.txt", "/system/root/poems/solstice.txt"),
    ("ozymandias.txt", "/system/root/poems/ozymandias.txt"),
    ("audio.wav", "/system/root/media/audio.wav"),
    ("video.mp4", "/system/root/media/video.mp4"),
]


def _seed_text_files(fs: VFS) -> None:
    for disk_name, vfs_path in _TEXT_FILE_SEEDS:
        content = (VFS_SEED_DIR / disk_name).read_text(encoding="utf-8")
        fs.write_file(vfs_path, content, user="root")


def seed_minimal(fs: VFS) -> None:
    """Creates a minimal directory structure so the terminal isn't
    completely empty on first boot. Called once at startup, before
    the Context is built."""
    fs.mkdir("/system", user="root")
    fs.mkdir("/system/hidden", user="root", hidden=True)
    fs.mkdir("/system/protected", user="root", protected=True)
    fs.mkdir("/system/root", user="root")
    fs.mkdir("/system/tmp", user="root")
    fs.mkdir("/system/logs", user="root")
    fs.mkdir("/system/root/poems", user="root")
    fs.mkdir("/system/root/media", user="root")
    _seed_text_files(fs)
