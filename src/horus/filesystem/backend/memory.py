from horus.filesystem.vfs import vfs
from horus.filesystem.node import Node, NodeType

class _TreeNode:

    def __init__(self, meta: Node, content: str= "", children: dict[str, "_TreeNode"] = None) -> None:
        self.meta = meta
        self.content = content
        self.children = children if children is not None else {}

class InMemoryVFS(VFS)
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
                raise ValueError("cannot resolve parent of root")

            parent_path = "/" + "/".join(segments[:-1])
            name = segments[-1]

            parent = self._walk(parent_path)
            if parent is None:
                raise FileNotFoundError(f"no such directory: {parent_path}")
            if parent.meta.type != NodeType.DIRECTORY:
                raise NotADirectoryError(parent_path)

            return parent, name



