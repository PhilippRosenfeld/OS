def resolve_path(path: str, cwd: str) -> str:
    """Combine cwd + path, collapse '.', '..', return a normalized
    absolute path starting with '/'. Shared by every VFS backend since
    path normalization doesn't depend on how nodes are actually stored."""
    if not cwd:
        raise ValueError("cwd must be provided")
    if not path:
        return cwd
    base = path if path.startswith("/") else cwd + "/" + path
    segments = [seg for seg in base.split("/") if seg not in ("", ".")]
    stack: list[str] = []
    for seg in segments:
        if seg == "..":
            if stack:
                stack.pop()
            # else: '..' past root -- silently ignore, stay at root
        else:
            stack.append(seg)
    return "/" + "/".join(stack)
