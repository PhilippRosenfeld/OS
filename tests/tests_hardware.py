from horus.hardware.spec import HardwareSpec


def test_defaults_when_nothing_loaded():
    spec = HardwareSpec()
    assert spec.cpu_cores == 1
    assert spec.memory_count == 2


def test_save_then_load_round_trips_all_fields(tmp_path):
    path = tmp_path / "hardware.json"
    spec = HardwareSpec(memory_kb="131072K", memory_count=4, cpu_mhz=4800,
                         cpu_cores=8, cpu_name="Test CPU", coolant_type="Liquid Nitrogen", coolant_amount=50)
    spec.save(path)

    loaded = HardwareSpec.load(path)
    assert loaded == spec


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "hardware.json"
    HardwareSpec().save(path)
    assert path.exists()


def test_load_missing_file_returns_defaults(tmp_path):
    spec = HardwareSpec.load(tmp_path / "does_not_exist.json")
    assert spec == HardwareSpec()
