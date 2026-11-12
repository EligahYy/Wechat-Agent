"""Open only regular files beneath the attachment root, without following symlinks."""
import os
from pathlib import Path
import stat


def open_attachment(data_dir,stored_path):
    if not isinstance(stored_path,(str,os.PathLike)):
        raise FileNotFoundError()
    base=Path(data_dir).resolve()
    root=base/'attachments'
    target=Path(stored_path)
    if target.is_absolute():
        try:target=target.relative_to(root)
        except ValueError:raise FileNotFoundError() from None
    parts=target.parts
    if not parts or any(part in ('..','.','') for part in parts):raise FileNotFoundError()
    directories=[];file_fd=None
    try:
        parent=os.open(base,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);directories.append(parent)
        for part in ('attachments',*parts[:-1]):
            parent=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent);directories.append(parent)
        file_fd=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        info=os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):raise FileNotFoundError()
        handle=os.fdopen(file_fd,'rb');file_fd=None
        return handle,info.st_size,parts[-1]
    except (OSError,ValueError):
        raise FileNotFoundError() from None
    finally:
        if file_fd is not None:os.close(file_fd)
        for directory in reversed(directories):os.close(directory)
