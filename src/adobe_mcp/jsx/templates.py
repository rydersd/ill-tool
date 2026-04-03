"""Reusable JSX fragments and escape helpers for ExtendScript."""


def escape_jsx_string(s: str) -> str:
    """Escape a Python string for safe embedding in a JSX string literal.

    Handles backslashes, quotes, whitespace, null bytes, Unicode line/paragraph
    separators, and other control characters that break ExtendScript strings.
    """
    import re

    # Remove null bytes — they terminate C strings and corrupt ExtendScript
    s = s.replace("\x00", "")

    # Remove other control characters (0x01-0x1F) except \n \r \t which
    # are handled explicitly below
    s = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", "", s)

    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace("\u2028", "\\u2028")  # Unicode line separator
        .replace("\u2029", "\\u2029")  # Unicode paragraph separator
    )


def escape_jsx_path(path: str) -> str:
    """Normalize a file path for use in JSX File() constructors.

    Converts Windows backslashes to forward slashes and escapes single quotes.
    """
    return path.replace("\\", "/").replace("'", "\\'")
