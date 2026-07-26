import yaml
from pathlib import Path

def load_config(path: str = "config/config.yaml") -> dict:
    with Path(path).open("r") as f:
        return yaml.safe_load(f)