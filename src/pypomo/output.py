"""Small helpers shared by timer and CLI output."""
import os
import sys


def safe_text(text: str, fallback: str | None = None) -> str:
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        if fallback is not None:
            return fallback
        return text.replace('·', '-').encode(encoding, errors='backslashreplace').decode(encoding)


def write(text: str, *, end: str = '\n') -> None:
    if sys.stdout is not None:
        print(safe_text(text), end=end, flush=True)


def silence_broken_pipe() -> None:
    """Prevent a second broken-pipe error during interpreter shutdown."""
    try:
        descriptor = sys.stdout.fileno()
    except (AttributeError, OSError, ValueError):
        return
    with open(os.devnull, 'w') as sink:
        os.dup2(sink.fileno(), descriptor)
