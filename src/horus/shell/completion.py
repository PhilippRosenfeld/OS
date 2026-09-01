from horus.filesystem.vfs import VFS


def complete_path(fs: VFS, cwd: str, prefix: str) -> list[str]:
    """Candidates for a path prefix being completed, e.g. for `cat`. If the
    prefix contains a '/' (e.g. 'root/p'), completes against that *named*
    directory instead of cwd, and candidates carry the directory part along
    ('root/poem.txt') so replacing the completed word reconstructs the full
    path, not just the bare name."""
    if "/" in prefix:
        dir_part, name_prefix = prefix.rsplit("/", 1)
        lookup_dir = fs.resolve_path(dir_part, cwd) if dir_part else "/"
    else:
        dir_part, name_prefix = "", prefix
        lookup_dir = cwd

    try:
        entries = fs.list_dir(lookup_dir)
    except Exception:
        return []

    matches = [e.name for e in entries if e.name.startswith(name_prefix)]
    if dir_part:
        return [f"{dir_part}/{name}" for name in matches]
    return matches
