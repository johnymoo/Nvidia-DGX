"""Small nested configuration lookup helper."""

MISSING = object()


def get_path(data, path, default=MISSING):
    current = data
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                if default is not MISSING:
                    return default
                raise KeyError(segment)
            current = current[segment]
        elif isinstance(current, list):
            try:
                current = current[int(segment)]
            except (ValueError, IndexError):
                if default is not MISSING:
                    return default
                raise
        else:
            if default is not MISSING:
                return default
            raise TypeError(f"cannot traverse {type(current).__name__}")
    return current
