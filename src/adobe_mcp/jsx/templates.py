"""Reusable JSX fragments and escape helpers for ExtendScript."""


def escape_jsx_string(s: str) -> str:
    """Escape a Python string for safe embedding in a JSX string literal.

    Handles double quotes, backslashes, and newlines — the common characters
    that break when interpolated into ExtendScript string literals.
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def escape_jsx_path(path: str) -> str:
    """Normalize a file path for use in JSX File() constructors.

    Converts Windows backslashes to forward slashes and escapes single quotes.
    """
    return path.replace("\\", "/").replace("'", "\\'")
