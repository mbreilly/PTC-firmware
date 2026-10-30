"""A template's data table: the values that go into its {fields}, one row per label.

    tpl["data"] = {
      "on": False,            # BATCH under PRINT: print the table instead of one label
      "main": "num",          # the MAIN column: it counts and orders the rows; the others follow it
      "count": 10,            # how many labels, when the main column is a sequence
      "advance": True,        # carry on numbering: sequences start after the last printed row next time
      "columns": [
        {"name": "num",  "mode": "sequence", "prefix": "", "start": 1, "step": 1, "digits": 3, "suffix": ""},
        {"name": "ip",   "mode": "ip", "start": "10.0.1.11", "step": 1},       # IP address, counts up
        {"name": "info", "mode": "fixed", "value": "PTC rev B"},               # the same on every label
        {"name": "note", "mode": "manual"},                                    # typed per row / from a CSV
      ],
      "rows": [{"note": "first board"}, ...],   # values of the manual columns, row by row
    }

Row i of every column belongs together: row 3 of the IP column goes with row 3 of the board number.
Older templates had a single-field "batch"; migrate() turns that into a table.
"""

import ipaddress
import re

MAX_ROWS = 500
MODES = ("sequence", "ip", "fixed", "manual")
NAME_OK = re.compile(r"^\w{1,40}$")


def blank(main: str = "num") -> dict:
    return {"on": False, "main": main, "count": 10, "advance": True,
            "columns": [column(main, "sequence")], "rows": []}


def column(name: str, mode: str = "manual", **kw) -> dict:
    base = {"sequence": {"prefix": "", "start": 1, "step": 1, "digits": 3, "suffix": ""},
            "ip": {"start": "10.0.0.1", "step": 1}, "fixed": {"value": ""}, "manual": {}}[mode]
    return {"name": name, "mode": mode, **base, **kw}


def migrate(tpl: dict, csv_rows=None) -> dict:
    """Give the template a data table, converting the old single-field "batch" if there is one.
    csv_rows(name) -> (columns, rows) is used for old CSV batches. Returns the template (changed in place)."""
    if isinstance(tpl.get("data"), dict) and tpl["data"].get("columns") is not None:
        return tpl
    old = tpl.pop("batch", None) or {}
    field = str(old.get("field") or "num")
    d = blank(field)
    d["on"] = bool(old.get("on"))
    d["advance"] = bool(old.get("advance", True))
    src = old.get("source", "range")
    if src == "range":
        d["columns"] = [column(field, "sequence", prefix=old.get("prefix", ""), start=int(old.get("start", 1)),
                               step=int(old.get("step", 1)) or 1, digits=int(old.get("digits", 3)),
                               suffix=old.get("suffix", ""))]
        d["count"] = int(old.get("count", 10))
    elif src == "csv" and old.get("csv") and csv_rows:
        try:
            cols, rows = csv_rows(old["csv"])
            fmap = old.get("map") or {}
            names = list(fmap) or cols
            d["columns"] = [column(n) for n in names]
            d["main"] = names[0] if names else field
            d["rows"] = [{n: r.get(fmap.get(n) or n, "") for n in names} for r in rows]
        except (OSError, ValueError):
            pass
    elif src == "list":
        d["columns"] = [column(field)]
        d["rows"] = [{field: l.strip()} for l in str(old.get("list", "")).splitlines() if l.strip()]
    tpl["data"] = d
    return tpl


def ensure_fields(d: dict, fields: list[str], test_values: dict) -> dict:
    """Every {field} the label uses gets a column (a new one is "fixed" at its test value)."""
    have = {c["name"] for c in d["columns"]}
    for f in fields:
        if f not in have:
            d["columns"].append(column(f, "fixed", value=str(test_values.get(f, ""))))
    if d.get("main") not in {c["name"] for c in d["columns"]} and d["columns"]:
        d["main"] = d["columns"][0]["name"]
    return d


def ip_add(start: str, n: int) -> str:
    try:
        ip = ipaddress.ip_address(str(start).strip())
    except ValueError:
        raise ValueError(f"{start!r} isn't an IP address.")
    try:
        return str(ip + int(n))
    except (ipaddress.AddressValueError, OverflowError):
        raise ValueError(f"{start} + {n} runs past the end of the address range.")


def value(c: dict, i: int, rows: list) -> str:
    m = c.get("mode")
    if m == "sequence":
        n = int(c.get("start", 1)) + i * (int(c.get("step", 1)) or 1)
        digits = max(0, min(12, int(c.get("digits", 0))))
        return f"{c.get('prefix', '')}{n:0{digits}d}{c.get('suffix', '')}"
    if m == "ip":
        return ip_add(c.get("start", "0.0.0.0"), i * (int(c.get("step", 1)) or 1))
    if m == "fixed":
        return str(c.get("value", ""))
    return str((rows[i] if i < len(rows) else {}).get(c["name"], "") or "")


def count(d: dict) -> int:
    main = next((c for c in d["columns"] if c["name"] == d.get("main")), None)
    if main is None:
        return 0
    if main["mode"] == "manual":
        filled = [i for i, r in enumerate(d.get("rows") or []) if str(r.get(main["name"], "")).strip()]
        return filled[-1] + 1 if filled else 0
    return max(0, int(d.get("count", 0)))


def resolve(tpl: dict, overrides: dict | None = None) -> tuple[list[dict], list[str]]:
    """The batch: one {field: value} per label, in the main column's order, plus warnings."""
    d = tpl["data"]
    n = count(d)
    if n > MAX_ROWS:
        raise ValueError(f"{n} labels is more than {MAX_ROWS} in one go; lower the count.")
    rows = d.get("rows") or []
    out, warn, missing = [], [], {}
    for i in range(n):
        r = {}
        for c in d["columns"]:
            r[c["name"]] = value(c, i, rows)
            if c["mode"] == "manual" and not r[c["name"]].strip():
                missing.setdefault(c["name"], []).append(i + 1)
        r.update(overrides or {})
        out.append(r)
    for name, idx in missing.items():
        warn.append(f"{{{name}}} is empty on {len(idx)} row(s): " + ", ".join(map(str, idx[:8])) + ("…" if len(idx) > 8 else ""))
    if not n:
        warn.append(f"The main column {{{d.get('main')}}} has no rows yet.")
    return out, warn


def advance(d: dict, printed: int) -> dict:
    """After printing `printed` rows: every sequence starts where it left off. Manual rows are kept."""
    for c in d["columns"]:
        step = int(c.get("step", 1)) or 1
        if c["mode"] == "sequence":
            c["start"] = int(c.get("start", 1)) + printed * step
        elif c["mode"] == "ip":
            c["start"] = ip_add(c.get("start", "0.0.0.0"), printed * step)
    return d


def check(d: dict) -> None:
    names = [c.get("name", "") for c in d.get("columns", [])]
    for n in names:
        if not NAME_OK.match(n):
            raise ValueError(f"Column name {n!r}: letters, digits and _ only (it's used as {{{n}}}).")
    if len(set(names)) != len(names):
        raise ValueError("Two columns have the same name.")
    for c in d.get("columns", []):
        if c.get("mode") not in MODES:
            raise ValueError(f"Column {c.get('name')}: unknown mode {c.get('mode')!r}.")
