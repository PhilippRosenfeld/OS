import sqlite3
from datetime import datetime
from pathlib import Path

from horus.filesystem.vfs import VFS
from horus.filesystem.node import Node, NodeType
from horus.filesystem.path_utils import resolve_path as _resolve_path


class SQLiteVFS(VFS):
    """SQLite-backed filesystem. Persists across app restarts: the schema is
    created on first use, and existing data is left alone on later opens --
    callers should check is_empty() before deciding whether to run the
    initial seed (see filesystem.seed), so a returning save isn't wiped."""

    def __init__(self, db_path: str | Path) -> None:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def is_empty(self) -> bool:
        """True if nothing besides the root directory has been created yet."""
        row = self._conn.execute("SELECT COUNT(*) AS n FROM nodes WHERE path != '/'").fetchone()
        return row["n"] == 0

    def _init_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                path TEXT PRIMARY KEY,
                parent_path TEXT,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('file', 'directory')),
                owner TEXT NOT NULL DEFAULT 'root',
                permissions TEXT NOT NULL DEFAULT 'rwxr-xr-x',
                created_at TEXT NOT NULL,
                modified_at TEXT NOT NULL,
                hidden INTEGER NOT NULL DEFAULT 0,
                size INTEGER NOT NULL DEFAULT 0,
                content TEXT
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_parent_path ON nodes(parent_path)")
        now = self._now()
        self._conn.execute(
            "INSERT OR IGNORE INTO nodes (path, parent_path, name, type, owner, permissions, created_at, modified_at, hidden, size) "
            "VALUES ('/', NULL, '/', 'directory', 'root', 'rwxr-xr-x', ?, ?, 0, 0)",
            (now, now),
        )
        self._conn.commit()

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        return Node(
            name=row["name"],
            type=NodeType(row["type"]),
            owner=row["owner"],
            permissions=row["permissions"],
            created_at=datetime.fromisoformat(row["created_at"]),
            modified_at=datetime.fromisoformat(row["modified_at"]),
            hidden=bool(row["hidden"]),
            size=row["size"],
        )

    def _fetch(self, path: str) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM nodes WHERE path = ?", (path,)).fetchone()

    def _parent_path(self, path: str) -> str:
        """Internal: the path of the parent directory for a non-root path."""
        segments = [seg for seg in path.split("/") if seg]
        if not segments:
            raise ValueError("Cannot resolve parent of root")
        return "/" + "/".join(segments[:-1])

    # --- path handling ---

    def resolve_path(self, path: str, cwd: str) -> str:
        return _resolve_path(path, cwd)

    # --- public methods ---

    def exists(self, path: str) -> bool:
        return self._fetch(path) is not None

    def list_dir(self, path: str, show_all: bool = False, recursive: bool = False) -> list[Node]:
        """Returns the content of a given directory as a list.
        show_all: include hidden entries (Node.hidden).
        recursive: also descend into subdirectories, flattening their entries into the same list."""
        row = self._fetch(path)
        if row is None:
            raise FileNotFoundError(path)
        if row["type"] != NodeType.DIRECTORY.value:
            raise NotADirectoryError(path)

        query = "SELECT * FROM nodes WHERE parent_path = ?"
        if not show_all:
            query += " AND hidden = 0"
        query += " ORDER BY name"
        children = self._conn.execute(query, (path,)).fetchall()

        entries: list[Node] = []
        for child in children:
            entries.append(self._row_to_node(child))
            if recursive and child["type"] == NodeType.DIRECTORY.value:
                child_path = path.rstrip("/") + "/" + child["name"]
                entries.extend(self.list_dir(child_path, show_all=show_all, recursive=True))
        return entries

    def read_file(self, path: str) -> str:
        """Reads the content of a file and returns it as a string."""
        row = self._fetch(path)
        if row is None or row["type"] != NodeType.FILE.value:
            raise FileNotFoundError(path)
        return row["content"] or ""

    def write_file(self, path: str, text: str) -> None:
        """Writes text to a file, creating it if it doesn't already exist."""
        parent_path = self._parent_path(path)
        if self._fetch(parent_path) is None:
            raise FileNotFoundError(f"no such directory: {parent_path}")
        name = path.rsplit("/", 1)[-1]
        now = self._now()
        if self.exists(path):
            self._conn.execute(
                "UPDATE nodes SET content = ?, size = ?, modified_at = ? WHERE path = ?",
                (text, len(text), now, path),
            )
        else:
            self._conn.execute(
                "INSERT INTO nodes (path, parent_path, name, type, owner, permissions, created_at, modified_at, hidden, size, content) "
                "VALUES (?, ?, ?, 'file', 'root', 'rwxr-xr-x', ?, ?, 0, ?, ?)",
                (path, parent_path, name, now, now, len(text), text),
            )
        self._conn.commit()

    def mkdir(self, path: str, hidden: bool = False) -> None:
        """Creates a directory at the given path."""
        parent_path = self._parent_path(path)
        if self._fetch(parent_path) is None:
            raise FileNotFoundError(f"no such directory: {parent_path}")
        if self.exists(path):
            raise FileExistsError(path)
        name = path.rsplit("/", 1)[-1]
        now = self._now()
        self._conn.execute(
            "INSERT INTO nodes (path, parent_path, name, type, owner, permissions, created_at, modified_at, hidden, size) "
            "VALUES (?, ?, ?, 'directory', 'root', 'rwxr-xr-x', ?, ?, ?, 0)",
            (path, parent_path, name, now, now, int(hidden)),
        )
        self._conn.commit()

    def get_meta(self, path: str) -> Node:
        row = self._fetch(path)
        if row is None:
            raise FileNotFoundError(path)
        return self._row_to_node(row)
