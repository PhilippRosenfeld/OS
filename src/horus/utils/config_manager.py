from pathlib import Path

import yaml


def load_config(path: str = "config/config.yaml") -> dict:
    with Path(path).open("r") as f:
        return yaml.safe_load(f)