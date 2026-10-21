"""Board photos (front and back of every board) and the ghost images used to line them up.

Every photo is kept in parameters.photo_dir on this computer as well as being uploaded to
the HWDB. The ghost images live in parameters.ghost_image_dir, one per side, and are shown
over the live camera view so every board is photographed in the same position.
"""

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from loguru import logger as lg

from ptctestsuite.config import parameters

SIDES = ("front", "back")
MIME_EXT = {"image/jpeg": ".jpg", "image/png": ".png"}
EXT_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


class PhotoError(ValueError):
    """The image can't be used. The message is shown to the tester."""


@dataclass
class Photo:
    side: str
    data: bytes
    mime: str
    source: str = "camera"   # camera or file

    @property
    def ext(self) -> str:
        return MIME_EXT[self.mime]


def _check(mime: str, data: bytes) -> None:
    if mime not in MIME_EXT:
        raise PhotoError("Use a JPEG or PNG image.")
    if not data:
        raise PhotoError("The image is empty.")
    if len(data) > parameters.photo_max_mb * 1024 * 1024:
        raise PhotoError(f"The image is larger than {parameters.photo_max_mb} MB.")
    # check the file really is what it says, so the HWDB doesn't get a broken image
    if mime == "image/jpeg" and not data.startswith(b"\xff\xd8"):
        raise PhotoError("That file isn't a valid JPEG image.")
    if mime == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise PhotoError("That file isn't a valid PNG image.")


_DATA_URL = re.compile(r"^data:([\w/+.-]+);base64,(.*)$", re.S)

def from_data_url(side: str, url: str, source: str = "camera") -> Photo:
    """Decodes an image sent by the GUI as a data: URL."""
    if side not in SIDES:
        raise PhotoError("Unknown board side.")
    m = _DATA_URL.match(url or "")
    if not m:
        raise PhotoError("No image was received. Take the photo again.")
    mime = "image/jpeg" if m.group(1) == "image/jpg" else m.group(1)
    try:
        data = base64.b64decode(m.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise PhotoError("The image arrived damaged. Take the photo again.")
    _check(mime, data)
    return Photo(side, data, mime, "file" if source == "file" else "camera")


def from_file(side: str, path: str | Path) -> Photo:
    """Reads an image file chosen by the tester (terminal mode)."""
    p = Path(path).expanduser()
    mime = EXT_MIME.get(p.suffix.lower())
    if mime is None:
        raise PhotoError("Use a .jpg or .png file.")
    try:
        data = p.read_bytes()
    except OSError as e:
        raise PhotoError(f"Can't read {p} ({e.strerror}).")
    _check(mime, data)
    return Photo(side, data, mime, "file")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._") or "board"


def save_board_photo(serial: str, photo: Photo) -> Path:
    """Keeps a copy of the photo on this computer and returns its path."""
    folder = Path(parameters.photo_dir)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{_safe(serial)}-{photo.side}-{stamp}{photo.ext}"
    path.write_bytes(photo.data)
    lg.info(f"Saved {photo.side} photo of {serial} to {path}")
    return path


# ---- ghost images ---------------------------------------------------------------

def ghost_path(side: str) -> Path | None:
    folder = Path(parameters.ghost_image_dir)
    for ext in (".jpg", ".png"):
        p = folder / f"{side}{ext}"
        if p.is_file():
            return p
    return None

def ghost_version(side: str) -> int | None:
    """Changes whenever the ghost changes, so the GUI knows to reload it. None if there is no ghost."""
    p = ghost_path(side)
    return p.stat().st_mtime_ns if p else None

def save_ghost(photo: Photo) -> Path:
    folder = Path(parameters.ghost_image_dir)
    folder.mkdir(parents=True, exist_ok=True)
    clear_ghost(photo.side)
    path = folder / f"{photo.side}{photo.ext}"
    path.write_bytes(photo.data)
    lg.info(f"Saved a new {photo.side} ghost image to {path}")
    return path

def clear_ghost(side: str) -> None:
    while (p := ghost_path(side)) is not None:
        p.unlink()
        lg.info(f"Removed the {side} ghost image {p}")
