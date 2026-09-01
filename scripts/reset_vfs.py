"""Deletes the persisted VFS database (saves/horus.db) so the next launch
re-seeds it from scratch via seed_minimal() (see src/horus/__init__.py). Run
this after adding/changing entries in src/horus/filesystem/seed.py -- e.g.
a new audio.wav seed -- since seed_minimal() only runs when the VFS is empty
and otherwise leaves an existing database untouched.

Run directly: `uv run python scripts/reset_vfs.py`
Skip the confirmation prompt: `uv run python scripts/reset_vfs.py --yes`
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from horus.paths import SAVES_DIR

VFS_DB_PATH = SAVES_DIR / "horus.db"


def main() -> None:
    if not VFS_DB_PATH.exists():
        print(f"Nothing to do -- {VFS_DB_PATH} does not exist.")
        return

    skip_confirm = "--yes" in sys.argv or "-y" in sys.argv
    if not skip_confirm:
        answer = input(f"Delete {VFS_DB_PATH} and reset the VFS to its seed state? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return

    VFS_DB_PATH.unlink()
    print(f"Deleted {VFS_DB_PATH}. It will be re-seeded on the next launch.")


if __name__ == "__main__":
    main()
