from horus.filesystem.vfs import VFS


def seed_minimal(fs: VFS) -> None:
    """Creates a minimal directory structure so the terminal isn't
    completely empty on first boot. Called once at startup, before
    the Context is built."""
    fs.mkdir("/home")
    fs.mkdir("/home/root")
    fs.mkdir("/home/root")
    fs.mkdir("/home/tmp")
    fs.write_file("/home/root/readme.txt", "welcome to horus.\n")