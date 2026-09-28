from horus.filesystem.backend.memory import InMemoryVFS
from horus.filesystem.disk_usage import drive_used_kb, ensure_mount_points, used_kb_by_mount_point
from horus.hardware.storage import Storage


def make_drive(name, mount_point):
    return Storage(name, 1024, "Test Inc.", power_usage_watts=3, mount_point=mount_point)


def make_fs_with_mounts(*mount_points):
    fs = InMemoryVFS()
    ensure_mount_points(fs, [make_drive(f"d{i}", m) for i, m in enumerate(mount_points)])
    return fs


def test_ensure_mount_points_creates_missing_parents_too():
    fs = InMemoryVFS()
    ensure_mount_points(fs, [make_drive("Root", "/"), make_drive("M.1", "/mnt/m1")])
    assert fs.exists("/mnt")
    assert fs.exists("/mnt/m1")


def test_ensure_mount_points_is_a_no_op_when_they_already_exist():
    fs = make_fs_with_mounts("/mnt/m1")
    fs.write_file("/mnt/m1/keep.txt", "x", user="root")
    ensure_mount_points(fs, [make_drive("M.1", "/mnt/m1")])
    assert fs.exists("/mnt/m1/keep.txt")


def test_files_count_towards_the_drive_they_are_mounted_on():
    fs = make_fs_with_mounts("/", "/mnt/m1", "/mnt/m2")
    fs.write_file("/root.txt", "a" * 1024, user="root")
    fs.write_file("/mnt/m1/one.txt", "b" * 2048, user="root")
    fs.write_file("/mnt/m2/two.txt", "c" * 4096, user="root")

    usage = used_kb_by_mount_point(fs, ["/", "/mnt/m1", "/mnt/m2"])

    assert usage == {"/": 1.0, "/mnt/m1": 2.0, "/mnt/m2": 4.0}   # nested mounts aren't counted twice


def test_deeply_nested_mounts_only_subtract_their_nearest_children():
    fs = make_fs_with_mounts("/", "/mnt/a", "/mnt/a/b")
    fs.write_file("/mnt/a/x.txt", "x" * 1024, user="root")
    fs.write_file("/mnt/a/b/y.txt", "y" * 1024, user="root")

    usage = used_kb_by_mount_point(fs, ["/", "/mnt/a", "/mnt/a/b"])

    assert usage == {"/": 0.0, "/mnt/a": 1.0, "/mnt/a/b": 1.0}


def test_a_sibling_directory_with_a_shared_prefix_is_not_under_the_mount():
    fs = make_fs_with_mounts("/", "/mnt/m1")
    fs.mkdir("/mnt/m10", user="root")
    fs.write_file("/mnt/m10/f.txt", "f" * 1024, user="root")

    usage = used_kb_by_mount_point(fs, ["/", "/mnt/m1"])

    assert usage == {"/": 1.0, "/mnt/m1": 0.0}


def test_drive_used_kb_keeps_drive_order_and_reports_unmounted_drives_as_empty():
    fs = make_fs_with_mounts("/", "/mnt/m1")
    fs.write_file("/mnt/m1/f.txt", "f" * 3072, user="root")
    unmounted = make_drive("Spare", None)

    assert drive_used_kb(fs, [make_drive("M.1", "/mnt/m1"), unmounted, make_drive("Root", "/")]) == [3.0, 0.0, 0.0]


def test_missing_mount_directory_and_missing_fs_count_as_empty():
    assert used_kb_by_mount_point(InMemoryVFS(), ["/mnt/nowhere"]) == {"/mnt/nowhere": 0.0}
    assert drive_used_kb(None, [make_drive("Root", "/")]) == [0.0]
