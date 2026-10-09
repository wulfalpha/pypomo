"""Small helpers shared by timer and CLI output."""
import errno
import os
import stat
import sys
from contextlib import contextmanager


def safe_text(text: str, fallback: str | None = None) -> str:
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        text.encode(encoding)
        return text
    except UnicodeEncodeError:
        if fallback is not None:
            return fallback
        return text.replace('·', '-').encode(encoding, errors='backslashreplace').decode(encoding)


@contextmanager
def _pipe_errors():
    """Normalize the Windows CRT's EINVAL for writes to a broken pipe only."""
    try:
        yield
    except OSError as exc:
        if sys.platform == 'win32' and exc.errno == errno.EINVAL:
            try:
                is_pipe = stat.S_ISFIFO(os.fstat(sys.stdout.fileno()).st_mode)
            except (AttributeError, OSError, ValueError):
                is_pipe = False
            if is_pipe:
                raise BrokenPipeError(errno.EPIPE, 'Broken output pipe') from exc
        raise


def write(text: str, *, end: str = '\n') -> None:
    if sys.stdout is not None:
        with _pipe_errors():
            print(safe_text(text), end=end, flush=True)


def flush() -> None:
    if sys.stdout is not None:
        with _pipe_errors():
            sys.stdout.flush()


def silence_broken_pipe() -> None:
    """Prevent a second broken-pipe error during interpreter shutdown."""
    try:
        descriptor = sys.stdout.fileno()
    except (AttributeError, OSError, ValueError):
        return
    with open(os.devnull, 'w') as sink:
        os.dup2(sink.fileno(), descriptor)
