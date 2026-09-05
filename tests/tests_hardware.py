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


# --- total_memory_kb / total_cpu_mhz (used to size ProcessTable's budget) ---

def test_total_memory_kb_multiplies_per_module_size_by_count():
    spec = HardwareSpec(memory_kb="16384K", memory_count=4)
    assert spec.total_memory_kb() == 65536


def test_total_memory_kb_with_default_spec():
    spec = HardwareSpec()  # memory_kb="65536K", memory_count=2
    assert spec.total_memory_kb() == 131072


def test_total_memory_kb_with_no_digits_is_zero():
    spec = HardwareSpec(memory_kb="unknown", memory_count=4)
    assert spec.total_memory_kb() == 0


def test_total_cpu_mhz_multiplies_mhz_by_cores():
    spec = HardwareSpec(cpu_mhz=4800, cpu_cores=8)
    assert spec.total_cpu_mhz() == 38400


def test_total_cpu_mhz_with_default_spec():
    spec = HardwareSpec()  # cpu_mhz=3200, cpu_cores=1
    assert spec.total_cpu_mhz() == 3200
