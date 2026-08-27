from horus.filesystem.vfs import VFS


def seed_minimal(fs: VFS) -> None:
    """Creates a minimal directory structure so the terminal isn't
    completely empty on first boot. Called once at startup, before
    the Context is built."""
    fs.mkdir("/home", user ="root",)
    fs.mkdir("/home/hidden", user ="root", hidden=True)
    fs.mkdir("/home/protected", user ="root", protected =True)
    fs.mkdir("/home/root", user ="root",)
    fs.mkdir("/home/tmp", user ="root",)
    fs.write_file("/home/root/readme.txt", "welcome to horus.\n", user ="root",)