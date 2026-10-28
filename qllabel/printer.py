"""Brother QL-810W raster protocol, written straight to /dev/usb/lp0 (no CUPS, no Brother driver).

The driver adds a 3 mm feed margin to every continuous label and refuses short lengths. Here the
margin (ESC i d) and the label length are just numbers we send, so the printer's own limits are the
only ones left. Command layout follows Brother's "QL-800/810W/820NWB Raster Command Reference"."""

import glob
import os
import select
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

DPI = 300
LINE_BYTES = 90            # the head has 720 pins; one raster line is always 90 bytes
VENDOR = "04f9"



@dataclass(frozen=True)
class Media:
    """One Brother roll. Sizes as Brother lists them (same numbers as brother_ql's label table)."""
    id: str
    width: int            # mm, what the printer reports
    length: int           # mm, 0 for continuous
    printable: int        # dots across
    right: int            # dots from the right-hand pin edge to the printable area
    printable_len: int = 0  # dots along, die-cut only
    kind: str = "continuous"   # continuous | die-cut | round

    @property
    def die_cut(self):
        return self.kind != "continuous"

    def name(self):
        if self.kind == "continuous":
            return f"{self.width} mm continuous"
        return f"{'Ø' if self.kind == 'round' else ''}{self.width}{'' if self.kind == 'round' else f' x {self.length}'} mm {self.kind}"


MEDIA = {m.id: m for m in [
    Media("12", 12, 0, 106, 29), Media("29", 29, 0, 306, 6), Media("38", 38, 0, 413, 12),
    Media("50", 50, 0, 554, 12), Media("54", 54, 0, 590, 0), Media("62", 62, 0, 696, 12),
    Media("17x54", 17, 54, 165, 0, 566, "die-cut"), Media("17x87", 17, 87, 165, 0, 956, "die-cut"),
    Media("23x23", 23, 23, 202, 42, 202, "die-cut"), Media("29x42", 29, 42, 306, 6, 425, "die-cut"),
    Media("29x90", 29, 90, 306, 6, 991, "die-cut"), Media("38x90", 38, 90, 413, 12, 991, "die-cut"),
    Media("39x48", 39, 48, 425, 6, 495, "die-cut"), Media("52x29", 52, 29, 578, 0, 271, "die-cut"),
    Media("62x29", 62, 29, 696, 12, 271, "die-cut"), Media("62x100", 62, 100, 696, 12, 1109, "die-cut"),
    Media("d12", 12, 12, 94, 113, 94, "round"), Media("d24", 24, 24, 236, 42, 236, "round"),
    Media("d58", 58, 58, 618, 51, 618, "round"),
]}
TAPES = {int(k): (m.printable, m.right) for k, m in MEDIA.items() if not m.die_cut}   # continuous widths


def media(mid) -> Media:
    m = MEDIA.get(str(mid))
    if not m:
        raise PrinterError(f"Unknown label media {mid!r}.")
    return m


def media_for(width: int, length: int, die_cut: bool) -> Media | None:
    """The roll matching what the printer reports as loaded."""
    for m in MEDIA.values():
        if m.width == width and m.die_cut == die_cut and (not die_cut or m.length == length):
            return m
    return None


MEDIA_TYPES = {0x00: "none", 0x0A: "continuous", 0x0B: "die-cut", 0x4A: "continuous", 0x4B: "die-cut"}
ERR1 = {0x01: "No media", 0x02: "End of media", 0x04: "Cutter jam", 0x10: "Printer in use",
        0x20: "Printer turned off", 0x40: "High-voltage adapter", 0x80: "Fan motor error"}
ERR2 = {0x01: "Replace media", 0x02: "Expansion buffer full", 0x04: "Communication error",
        0x08: "Communication buffer full", 0x10: "Cover open", 0x20: "Cancel key pressed",
        0x40: "Media cannot be fed", 0x80: "System error"}
STATUS_TYPES = {0x00: "reply", 0x01: "printing done", 0x02: "error", 0x04: "turned off",
                0x05: "notification", 0x06: "phase change"}


class PrinterError(Exception):
    pass


def mm_to_dots(mm: float) -> int:
    return round(mm * DPI / 25.4)


def dots_to_mm(d: float) -> float:
    return d * 25.4 / DPI


def find_device() -> str | None:
    """The /dev/usb/lpN whose USB device is a Brother."""
    for lp in sorted(glob.glob("/sys/class/usbmisc/lp*")):
        p = Path(lp).resolve()
        for parent in [p, *p.parents]:
            vid = parent / "idVendor"
            if vid.exists():
                if vid.read_text().strip() == VENDOR:
                    return "/dev/usb/" + Path(lp).name
                break
    return None


@dataclass
class Status:
    raw: bytes
    errors: list = field(default_factory=list)
    media_width: int = 0
    media_type: str = "none"
    media_length: int = 0
    status_type: str = ""
    phase: int = 0

    @classmethod
    def parse(cls, d: bytes) -> "Status":
        if len(d) < 32 or d[0] != 0x80:
            raise PrinterError(f"Odd status reply from the printer: {d.hex(' ')}")
        errs = [m for b, m in ERR1.items() if d[8] & b] + [m for b, m in ERR2.items() if d[9] & b]
        return cls(raw=d[:32], errors=errs, media_width=d[10], media_type=MEDIA_TYPES.get(d[11], hex(d[11])),
                   media_length=d[17], status_type=STATUS_TYPES.get(d[18], hex(d[18])), phase=d[19])

    @property
    def media(self) -> Media | None:
        return media_for(self.media_width, self.media_length, self.media_type == "die-cut")

    def as_dict(self):
        m = self.media
        return {"errors": self.errors, "media_width": self.media_width, "media_type": self.media_type,
                "media_length": self.media_length, "media": m.id if m else None,
                "media_name": m.name() if m else f"{self.media_width} mm {self.media_type} (unknown roll)",
                "status_type": self.status_type, "phase": self.phase}


@dataclass
class JobOptions:
    media: str = "29"
    margin: int = 35          # ESC i d feed margin in dots (Brother's driver always uses 35 = 3 mm)
    cut: str = "each"         # each | end | none
    cut_every: int = 1        # with cut="each": cut after every N labels
    quality: bool = True      # print priority: quality over speed


def raster_lines(img: Image.Image, tape) -> bytes:
    """One label image (width = printable dots across the tape, height = length in dots) -> raster data.
    Black pixels print, mirrored into the `right` .. `right + printable` pins of the 720-pin line (byte-for-byte the
    same as brother_ql produces; mirroring it onto the far end of the head printed nothing on 29 mm tape)."""
    m = media(tape)
    printable, right = m.printable, m.right
    if img.width != printable:
        raise PrinterError(f"Image is {img.width} dots wide; {m.name()} takes {printable}.")
    g = img.convert("L")
    full = Image.new("L", (LINE_BYTES * 8, g.height), 255)
    full.paste(ImageOps.mirror(g), (right, 0))
    bits = ImageOps.invert(full).point(lambda v: 255 if v >= 128 else 0).convert("1")   # 1 bit = print
    data = bits.tobytes()
    out = bytearray()
    for y in range(g.height):
        out += b"g\x00" + bytes([LINE_BYTES]) + data[y * LINE_BYTES:(y + 1) * LINE_BYTES]
    return bytes(out)


def build_job(pages: list[Image.Image], opt: JobOptions) -> bytes:
    """All pages in one job. Each page is a label image, already turned so its height runs along the tape."""
    if not pages:
        raise PrinterError("Nothing to print.")
    m = media(opt.media)
    out = bytearray(b"\x00" * 400 + b"\x1b@")          # invalidate, then initialise
    for i, img in enumerate(pages):
        lines = img.height
        out += b"\x1bia\x01"                            # raster mode
        flags = 0x02 | 0x04 | 0x08 | 0x80 | (0x40 if opt.quality else 0)   # type, width, length valid; recover
        if m.die_cut and lines != m.printable_len:
            raise PrinterError(f"{m.name()} labels are {m.printable_len} dots long, not {lines}.")
        out += b"\x1biz" + bytes([flags, 0x0B if m.die_cut else 0x0A, m.width, m.length]) + lines.to_bytes(4, "little") \
            + bytes([0 if i == 0 else 1, 0])
        out += b"\x1biM" + bytes([0x40 if opt.cut == "each" else 0])          # auto cut
        out += b"\x1biA" + bytes([max(1, min(255, opt.cut_every))])
        out += b"\x1biK" + bytes([0x08 if opt.cut in ("each", "end") else 0])  # cut at end of job
        margin = 0 if m.die_cut else max(0, min(65535, opt.margin))      # die-cut labels feed to their own gap
        out += b"\x1bid" + margin.to_bytes(2, "little")
        out += b"M\x00"                                  # no compression
        out += raster_lines(img, m.id)
        out += b"\x1a" if i == len(pages) - 1 else b"\x0c"
    return bytes(out)


class Printer:
    def __init__(self, device: str | None = None, dry_run_dir: Path | None = None):
        self.device = device
        self.dry_run_dir = dry_run_dir

    def path(self) -> str:
        dev = self.device or find_device()
        if not dev:
            raise PrinterError("No Brother printer on USB. Is it plugged in and switched on?")
        if not os.access(dev, os.R_OK | os.W_OK):
            raise PrinterError(f"No permission for {dev}: user must be in the 'lp' group (or start with sg lp).")
        return dev

    def _open(self):
        return os.open(self.path(), os.O_RDWR)

    @staticmethod
    def _read_status(fd, timeout: float) -> Status | None:
        end = time.monotonic() + timeout
        buf = b""
        while time.monotonic() < end:
            r, _, _ = select.select([fd], [], [], max(0.0, min(0.2, end - time.monotonic())))
            if r:
                chunk = os.read(fd, 32 - len(buf))
                buf += chunk
                if len(buf) >= 32:
                    return Status.parse(buf)
                if not chunk:
                    time.sleep(0.05)
        return None

    @staticmethod
    def _write_all(fd, data: bytes):
        view = memoryview(data)
        while view:
            n = os.write(fd, view[:16384])
            view = view[n:]

    def status(self) -> Status:
        if self.dry_run_dir:
            return Status(raw=b"", media_width=29, media_type="continuous", status_type="dry run")
        fd = self._open()
        try:
            self._write_all(fd, b"\x00" * 400 + b"\x1b@\x1biS")
            st = self._read_status(fd, 3.0)
        finally:
            os.close(fd)
        if not st:
            raise PrinterError("The printer did not answer a status request.")
        return st

    def print_job(self, pages: list[Image.Image], opt: JobOptions, timeout_per_page: float = 20.0) -> dict:
        job = build_job(pages, opt)
        if self.dry_run_dir:
            self.dry_run_dir.mkdir(parents=True, exist_ok=True)
            f = self.dry_run_dir / time.strftime("job-%Y%m%d-%H%M%S.bin")
            f.write_bytes(job)
            return {"ok": True, "pages": len(pages), "dry_run": str(f), "bytes": len(job)}
        before = self.status()
        if before.errors:
            raise PrinterError("Printer reports: " + ", ".join(before.errors))
        want = media(opt.media)
        if before.media_width and before.media is not want:
            raise PrinterError(f"The printer has {before.as_dict()['media_name']} loaded; this label is for {want.name()}.")
        fd = self._open()
        done = 0
        try:
            self._write_all(fd, job)
            end = time.monotonic() + timeout_per_page * len(pages)
            while done < len(pages) and time.monotonic() < end:
                st = self._read_status(fd, end - time.monotonic())
                if not st:
                    break
                if st.status_type == "error" or st.errors:
                    raise PrinterError("Printer stopped: " + (", ".join(st.errors) or "error"))
                if st.status_type == "printing done":
                    done += 1
        finally:
            os.close(fd)
        if done < len(pages):
            raise PrinterError(f"Printer confirmed only {done} of {len(pages)} labels.")
        return {"ok": True, "pages": len(pages), "bytes": len(job)}
