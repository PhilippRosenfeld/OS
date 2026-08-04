from horus.filesystem.vfs import VFS
from horus.filesystem.node import Node, NodeType

class _TreeNode:

    def __init__(self, meta: Node, content: str= "", children: dict[str, "_TreeNode"] = None) -> None:
        self.meta = meta
        self.content = content
        self.children = children if children is not None else {}

class InMemoryVFS(VFS):
    def __init__(self) -> None:
        self._root= _TreeNode(Node(name="/", type=NodeType.DIRECTORY))

    # --- path handling -------------------------------------------------------

    def resolve_path(self, path: str, cwd: str) -> str:
        """Combine cwd + path, collapse '.', '..', return a normalized
        absolute path starting with '/'."""
        if not cwd:
            raise ValueError(f"cwd must be provided")
        if not path:
            return cwd
        base = path if path.startswith("/") else cwd + "/" + path
        segments = [seg for seg in base.split("/") if seg not in ("", ".")]
        stack: list[str] = []
        for seg in segments:
            if seg == "..":
                if stack:
                    stack.pop()
                # else: '..' past root — silently ignore, stay at root
            else:
                stack.append(seg)
        return "/" + "/".join(stack)

    def _walk(self, path:str) -> _TreeNode | None:
        """Internal: traverse the tree from root along the segments of
        an already-resolved absolute path. Returns None if any segment
        is missing."""
        segments = [seg for seg in path.split("/") if seg]
        node = self._root
        for seg in segments:
            if node.meta.type != NodeType.DIRECTORY:
                return None
            node = node.children.get(seg)
            if node is None:
                return None
        return node

    def _parent_and_name(self, path: str) -> tuple[_TreeNode, str]:
        """Internal: resolve the parent directory node and final segment
        name for a path, raising if the parent doesn't exist."""
        segments = [seg for seg in path.split("/") if seg]
        if not segments:
            raise ValueError("Cannot resolve parent of root")
        parent_path = "/" + "/".join(segments[:-1])
        name = segments[-1]
        parent = self._walk(parent_path)
        if parent is None:
            raise FileNotFoundError(f"no such directory: {parent_path}")
        if parent.meta.type != NodeType.DIRECTORY:
            raise NotADirectoryError(parent_path)

        return parent, name

    # --- public methods -------------------------------------------
    def exists(self, path: str) -> bool:
        """Checks if a given path exists"""
        return self._walk(path) is not None

    def list_dir(self, path: str, show_all: bool = False, recursive: bool = False) -> list[Node]:
        """Returns the content of a given directory as a list.
        show_all: include hidden entries (Node.hidden).
        recursive: also descend into subdirectories, flattening their entries into the same list."""
        cur_node = self._walk(path)

        if cur_node is None:
            raise FileNotFoundError(path)
        
        if cur_node.meta.type != NodeType.DIRECTORY:
            raise NotADirectoryError(path)

        entries: list[Node] = []
        for name, child in cur_node.children.items():
            if not show_all and child.meta.hidden:
                continue
            entries.append(child.meta)
            if recursive and child.meta.type == NodeType.DIRECTORY:
                child_path = path.rstrip("/") + "/" + name
                entries.extend(self.list_dir(child_path, show_all=show_all, recursive=True))

        return entries

    def read_file(self, path: str) -> str:
        """Reads the content of a file and returns it as a string.
        #TODO: Implement handlers for different file types"""
        file = self._walk(path)

        if file is None or file.meta.type != NodeType.FILE:
            raise FileNotFoundError(path)
        
        return file.content

    def write_file(self, path: str, text: str) -> None:
        """Writes text in a file.
        #TODO: Implement handlers for different file types"""
        parent, name = self._parent_and_name(path)
        existing = parent.children.get(name)

        if existing is None:
            meta = Node(name=name, type=NodeType.FILE, size=len(text))
            parent.children[name] = _TreeNode(meta, content=text)
        else:
            existing.content = text
            existing.meta.size = len(text)

    def mkdir(self, path: str) -> None:
        """Creates a directory at the given path."""
        parent, name = self._parent_and_name(path)
        if name in parent.children:
            raise FileExistsError(path)
        parent.children[name] = _TreeNode(Node(name=name, type=NodeType.DIRECTORY))

    def get_meta(self, path: str) -> None:
        node = self._walk(path)
        if node is None:
            raise FileNotFoundError(path)
        return node.meta
