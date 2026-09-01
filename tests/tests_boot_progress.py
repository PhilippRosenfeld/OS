from horus.story.progress import BootProgress


# --- status / mark_ok / mark_failed ---

def test_status_defaults_to_failed_for_unknown_sector():
    progress = BootProgress()
    assert progress.status("disk1_1") == "FAILED"


def test_mark_ok_flips_status_to_ok():
    progress = BootProgress()
    progress.mark_ok("disk1_1")
    assert progress.status("disk1_1") == "OK"


def test_mark_failed_flips_status_back_to_failed():
    progress = BootProgress()
    progress.mark_ok("disk1_1")
    progress.mark_failed("disk1_1")
    assert progress.status("disk1_1") == "FAILED"


# --- latest_ok_disk ---

def test_latest_ok_disk_with_nothing_marked_returns_none():
    progress = BootProgress()
    assert progress.latest_ok_disk() is None


def test_latest_ok_disk_requires_every_sector_of_a_disk():
    progress = BootProgress()
    progress.mark_ok("disk1_1")
    progress.mark_ok("disk1_2")
    # disk1_3 never marked -- disk 1 isn't fully OK yet
    assert progress.latest_ok_disk() is None


def test_latest_ok_disk_returns_the_highest_fully_ok_disk():
    progress = BootProgress()
    for sector in (1, 2, 3):
        progress.mark_ok(f"disk1_{sector}")
        progress.mark_ok(f"disk2_{sector}")
    assert progress.latest_ok_disk() == 2


def test_latest_ok_disk_stops_at_the_first_incomplete_disk():
    """Disks load in order -- a fully-OK disk 3 doesn't count if disk 2 is
    incomplete, since load order means disk 3 would never actually be reached."""
    progress = BootProgress()
    for sector in (1, 2, 3):
        progress.mark_ok(f"disk1_{sector}")
        progress.mark_ok(f"disk3_{sector}")
    # disk2 sectors never marked
    assert progress.latest_ok_disk() == 1


def test_latest_ok_disk_respects_custom_disk_count_and_sectors():
    progress = BootProgress()
    progress.mark_ok("disk1_1")
    assert progress.latest_ok_disk(disk_count=1, sectors_per_disk=1) == 1


# --- save / load ---

def test_save_then_load_round_trips_disk_state(tmp_path):
    path = tmp_path / "boot_progress.json"
    progress = BootProgress()
    progress.mark_ok("disk1_1")
    progress.mark_ok("disk1_2")
    progress.save(path)

    loaded = BootProgress.load(path)
    assert loaded.status("disk1_1") == "OK"
    assert loaded.status("disk1_2") == "OK"
    assert loaded.status("disk1_3") == "FAILED"


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "boot_progress.json"
    BootProgress().save(path)
    assert path.exists()


def test_load_missing_file_returns_a_fresh_instance(tmp_path):
    progress = BootProgress.load(tmp_path / "does_not_exist.json")
    assert progress.disks == {}
    assert progress.latest_ok_disk() is None
