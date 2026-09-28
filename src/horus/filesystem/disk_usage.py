"""Which drive a VFS file takes up space on: every drive (see
hardware.storage.Storage) is mounted at a VFS directory (its mount_point),
and a file belongs to the drive with the longest mount point that's a
prefix of its path -- the same rule as Unix mounts, so e.g. /mnt/m1/a.txt
lands on the drive mounted at /mnt/m1, not on the one mounted at /."""

from horus.filesystem.node import NodeType
from horus.filesystem.vfs import VFS


def _normalize(mount_point: str) -> str:
    return "/" + mount_point.strip("/") if mount_point.strip("/") else "/"


def _is_under(path: str, mount_point: str) -> bool:
    """Whether `path` is `mount_point` itself or somewhere below it."""
    if mount_point == "/":
        return True
    return path == mount_point or path.startswith(mount_point + "/")


def _total_bytes(fs: VFS, directory: str) -> int:
    """Size of every file under `directory` (recursive, hidden included) --
    0 if it doesn't exist (yet)."""
    try:
        return sum(node.size for node in fs.list_dir(directory, show_all=True, recursive=True)
                   if node.type == NodeType.FILE)
    except (FileNotFoundError, NotADirectoryError):
        return 0


def used_kb_by_mount_point(fs: VFS | None, mount_points: list[str]) -> dict[str, float]:
    """KB used on each mount point: everything under it, minus whatever
    lies under a deeper mount point inside it (that belongs to the deeper
    one's drive instead, so nothing is counted twice)."""
    mounts = sorted({_normalize(m) for m in mount_points}, key=len)
    if fs is None:
        return {m: 0.0 for m in mounts}
    totals = {m: _total_bytes(fs, m) for m in mounts}
    used = {}
    for mount in mounts:
        nested = [m for m in mounts if m != mount and _is_under(m, mount)]
        # only the nearest nested mounts -- a deeper one inside those is
        # already excluded from their own totals' share below
        nearest = [m for m in nested if not any(o != m and _is_under(m, o) for o in nested)]
        used[mount] = (totals[mount] - sum(totals[m] for m in nearest)) / 1024
    return used


def drive_used_kb(fs: VFS | None, drives) -> list[float]:
    """KB used on each of `drives` (same order), by their mount_point --
    0 for a drive that isn't mounted."""
    usage = used_kb_by_mount_point(fs, [d.mount_point for d in drives if d.mount_point is not None])
    return [usage[_normalize(d.mount_point)] if d.mount_point is not None else 0.0 for d in drives]


def ensure_mount_points(fs: VFS, drives, user: str = "root") -> None:
    """Creates every drive's mount point directory (and any missing parent,
    e.g. /mnt) in the VFS if it doesn't exist yet -- also for an existing
    save that predates mount points or a newly added drive."""
    for drive in drives:
        if drive.mount_point is None:
            continue
        path = ""
        for part in _normalize(drive.mount_point).strip("/").split("/"):
            if not part:
                continue
            path += "/" + part
            if not fs.exists(path):
                fs.mkdir(path, user=user)
