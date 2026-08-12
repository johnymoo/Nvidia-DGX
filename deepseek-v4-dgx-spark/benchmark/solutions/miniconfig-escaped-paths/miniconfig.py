"""Small nested configuration lookup helper."""

MISSING = object()


def _segments(path):
    segments = []
    current = []
    escaped = False
    for char in path:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ".":
            if not current:
                raise ValueError("path contains an empty segment")
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        raise ValueError("path ends with a dangling escape")
    if not current:
        raise ValueError("path contains an empty segment")
    segments.append("".join(current))
    return segments


def get_path(data, path, default=MISSING):
    current = data
    for segment in _segments(path):
        if isinstance(current, dict):
            if segment not in current:
                if default is not MISSING:
                    return default
                raise KeyError(segment)
            current = current[segment]
        elif isinstance(current, list):
            if not segment.isdecimal():
                raise TypeError(f"list segment is not an index: {segment!r}")
            index = int(segment)
            if index >= len(current):
                if default is not MISSING:
                    return default
                raise IndexError(index)
            current = current[index]
        else:
            raise TypeError(f"cannot traverse {type(current).__name__}")
    return current
