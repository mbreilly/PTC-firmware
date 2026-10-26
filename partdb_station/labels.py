"""Read what a part label's barcode says.

Understands the codes on distributor labels and bags:
  * ECIA / EIGP 114 "format 06" DataMatrix (DigiKey, Mouser, Newark/element14, Arrow, most others)
  * LCSC's QR code  {pbn:...,on:...,pc:C2040,pm:RP2040,qty:10,...}
  * TME's QR code   QTY:10 PN:... MFR:... MPN:... PO:... https://www.tme.eu/...
  * Part-DB's own labels (https://.../scan/part/12, P0012, L0034, S0005)
  * a distributor product link, an EAN/UPC number, or plain text (taken as a part number)

A USB scanner acting as a keyboard often can't type the invisible separators in a format 06 code
(GS = 0x1D, RS = 0x1E, EOT = 0x04). The page turns Ctrl+] / Ctrl+^ / Ctrl+D into them, and this
file also accepts the visible stand-ins some scanners and decoders send: ␝ ␞ ␄, <GS> {GS} [GS] ^].
"""

import re
from urllib.parse import unquote, urlparse

GS, RS, EOT = "\x1d", "\x1e", "\x04"
_STANDINS = [("␝", GS), ("␞", RS), ("␄", EOT)]
for _name, _ch in (("GS", GS), ("RS", RS), ("EOT", EOT)):
    for _fmt in ("<{}>", "{{{}}}", "[{}]"):
        _STANDINS.append((_fmt.format(_name), _ch))
_STANDINS += [("^]", GS), ("^^", RS)]

# EIGP 114 data identifiers worth showing, and what they mean
ECIA_NAMES = {
    "P": "Customer part no.", "1P": "Manufacturer part no.", "30P": "DigiKey part no.", "3P": "Supplier part no.",
    "Q": "Quantity", "K": "Customer PO", "1K": "Sales order", "10K": "Invoice", "11K": "Invoice", "14K": "PO line",
    "1T": "Lot", "9D": "Date code (YYWW)", "10D": "Date code (YYWW)", "4L": "Country of origin", "1V": "Manufacturer",
    "11Z": "DigiKey PICK", "12Z": "DigiKey part ID", "13Z": "DigiKey load ID", "20Z": "DigiKey padding",
}

# product links we can pull a part number out of
_URL_RULES = [
    ("digikey", re.compile(r"digikey\.[a-z.]+/.*?/detail/[^/]+/([^/]+)/(\d+)", re.I), "mpn_id"),
    ("mouser", re.compile(r"mouser\.[a-z.]+/ProductDetail/(?:[^/]+/)?([^/?#]+)", re.I), "mpn"),
    ("lcsc", re.compile(r"lcsc\.com/.*?(C\d{3,})", re.I), "spn"),
    ("tme", re.compile(r"tme\.eu/[^/]+/details/([^/?#]+)", re.I), "spn"),
]


def _clean(raw: str) -> str:
    s = raw.replace("\r", "").replace("\n", "")
    for a, b in _STANDINS:
        s = s.replace(a, b)
    return s.strip(" \t")


def _blank():
    return {"mpn": "", "spn": "", "manufacturer": "", "qty": None, "po": "", "order": "", "lot": "",
            "date_code": "", "country": "", "url": "", "gtin": "", "description": ""}


def parse(raw: str) -> dict:
    """Returns {"kind", "vendor", "fields": [[label, value], ...], "part": {...}, "partdb": {...} or None}."""
    s = _clean(raw)
    for fn in (_ecia, _lcsc, _tme, _partdb, _url, _gtin):
        r = fn(s)
        if r:
            return r
    part = _blank()
    part["mpn"] = s.strip()
    return {"kind": "text", "vendor": "", "fields": [["Text", s]], "part": part, "partdb": None}


def _ecia(s: str):
    m = re.match(r"^>?\[\)>" + RS + r"?06" + GS, s)
    if not m:
        return None
    body = s[m.end():]
    data, fields = {}, []
    for chunk in re.split("[" + GS + RS + EOT + "]", body):
        chunk = chunk.strip()
        if not chunk:
            continue
        dm = re.match(r"^0*([1-9]?\d*[A-Z])(.*)$", chunk)
        if not dm:
            continue
        di, val = dm.group(1), dm.group(2).strip()
        data.setdefault(di, val)
        fields.append([f"{ECIA_NAMES.get(di, 'Field')} ({di})", val])

    vendor = ""
    if any(k in data for k in ("11Z", "12Z", "13Z", "20Z", "30P")):
        vendor = "digikey"
    elif "14K" in data or "1V" in data:
        vendor = "mouser"
    elif "3P" in data:
        vendor = "element14"

    part = _blank()
    part["mpn"] = data.get("1P", "")
    part["spn"] = data.get("30P") or data.get("3P") or (data.get("P", "") if vendor == "digikey" else "")
    if vendor == "mouser" and data.get("1V"):
        part["manufacturer"] = data["1V"]
    part["qty"] = _int(data.get("Q"))
    part["po"] = data.get("K", "")
    part["order"] = data.get("1K") or data.get("10K") or data.get("11K", "")
    part["lot"] = data.get("1T", "")
    part["date_code"] = data.get("10D") or data.get("9D", "")
    part["country"] = data.get("4L", "")
    if not part["mpn"] and not part["spn"]:
        part["mpn"] = data.get("P", "")
    return {"kind": "ecia", "vendor": vendor, "fields": fields, "part": part, "partdb": None}


def _lcsc(s: str):
    m = re.match(r"^\{(.*)\}$", s, re.S)
    if not m or "pc:" not in s and "pm:" not in s:
        return None
    data = {}
    for item in m.group(1).split(","):
        k, _, v = item.partition(":")
        if k.strip():
            data[k.strip()] = v.strip()
    names = {"pc": "LCSC part no.", "pm": "Manufacturer part no.", "qty": "Quantity", "on": "Order no.",
             "pbn": "Pick batch", "mc": "Manufacturer code", "cc": "Country / channel", "wc": "Warehouse"}
    part = _blank()
    part["spn"] = data.get("pc", "")
    part["mpn"] = data.get("pm", "")
    part["qty"] = _int(data.get("qty"))
    part["order"] = data.get("on", "")
    part["lot"] = data.get("pbn", "")
    fields = [[f"{names.get(k, 'Field')} ({k})", v] for k, v in data.items()]
    return {"kind": "lcsc", "vendor": "lcsc", "fields": fields, "part": part, "partdb": None}


def _tme(s: str):
    if "tme.eu" not in s.lower():
        return None
    data = {}
    for tok in s.split():
        if tok.lower().startswith("http"):
            data["URL"] = tok
        elif ":" in tok:
            k, _, v = tok.partition(":")
            data[k.upper()] = v
    part = _blank()
    part["spn"] = data.get("PN", "")
    part["mpn"] = data.get("MPN", "")
    part["manufacturer"] = data.get("MFR", "")
    part["qty"] = _int(data.get("QTY"))
    part["po"] = data.get("PO", "")
    part["country"] = data.get("COO", "")
    part["url"] = data.get("URL", "")
    return {"kind": "tme", "vendor": "tme", "fields": [[k, v] for k, v in data.items()], "part": part, "partdb": None}


def _partdb(s: str):
    kinds = {"P": "part", "L": "lot", "S": "location", "part": "part", "lot": "lot", "location": "location"}
    m = (re.match(r"^https?://.*/scan/(\w+)/(\d+)/?$", s) or re.match(r"^([PLS])(\d{4,})$", s)
         or re.match(r"^([PLS])-(\d{6,})$", s))
    if not m or m.group(1) not in kinds:
        return None
    ref = {"type": kinds[m.group(1)], "id": int(m.group(2))}
    return {"kind": "partdb", "vendor": "", "fields": [["Part-DB label", f"{ref['type']} {ref['id']}"]],
            "part": _blank(), "partdb": ref}


def _url(s: str):
    if not re.match(r"^https?://", s, re.I):
        return None
    for vendor, rx, what in _URL_RULES:
        m = rx.search(s)
        if m:
            part = _blank()
            part["url"] = s
            if what == "mpn_id":
                part["mpn"] = unquote(m.group(1))
            elif what == "mpn":
                part["mpn"] = unquote(m.group(1))
            else:
                part["spn"] = unquote(m.group(1))
            return {"kind": "url", "vendor": vendor, "fields": [["Link", s]], "part": part, "partdb": None}
    part = _blank()
    part["url"] = s
    part["mpn"] = unquote(urlparse(s).path.rstrip("/").rsplit("/", 1)[-1])
    return {"kind": "url", "vendor": "", "fields": [["Link", s]], "part": part, "partdb": None}


def _gtin(s: str):
    if not re.fullmatch(r"\d{8}|\d{12,14}", s):
        return None
    part = _blank()
    part["gtin"] = s
    return {"kind": "gtin", "vendor": "", "fields": [["EAN / UPC", s]], "part": part, "partdb": None}


def _int(v):
    try:
        return int(float(str(v).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
