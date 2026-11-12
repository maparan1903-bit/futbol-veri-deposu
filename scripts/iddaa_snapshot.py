"""iddaa odds snapshot for the GitHub data repo (runs in GitHub Actions while the PC is off; standard library only).

One request reads iddaa.com's own pre-match bulletin (the same address fi.sources.iddaa polls). Only the tracked
competitions, the priced market subtypes and matches kicking off within WINDOW are kept, and only quotes whose
price or MBS changed since the last file of the same UTC day are written: the first run of a day writes every
quote once (a baseline), later runs write just the changes. Output: data/iddaa/<YYYY-MM-DD>/<HHMMSS>.csv.gz plus
that day's index.txt listing the files in order. The local program (fi.sources.iddaa_mirror) imports the files.

Read-only price collection for personal analysis; no bets, no login, no personal data.
The id lists below must equal fi.sources.iddaa.COMPETITIONS / SUBTYPES (tests/test_iddaa_mirror.py checks this).

Usage: python iddaa_snapshot.py [--root data/iddaa] [--input bulletin.json] [--now 2026-11-12T19:00:00]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import shutil
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

FEED_URL = "https://sportsbookv2.iddaa.com/sportsbook/events?st=1&type=0&version=0"
USER_AGENT = "football-intelligence/0.1 (personal research)"
TIMEOUT_S = 60
WINDOW = timedelta(hours=72)  # closing prices matter; matches further out are caught once they enter the window
KEEP_DAYS = 10  # older day folders leave the working tree (git history keeps them); the importer looks back 8 days
COLUMNS = ["e", "c", "d", "h", "a", "st", "sov", "mbs", "n", "odd"]
INDEX = "index.txt"
COMPETITIONS = frozenset({584, 43, 52, 129, 45, 143, 381, 322, 566, 148, 262, 149, 24, 12, 132, 1774, 1951, 614,
                          46194, 46195, 46196, 1407})
SUBTYPES = frozenset({1, 92, 89, 101, 88, 60, 603, 604, 100, 4, 90, 91, 7, 698, 700, 699, 36, 77, 720, 722, 723, 6})

Key = tuple[str, str, str, str]  # event id, subtype, line, option name


def fetch() -> bytes:
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed https address
        return bytes(resp.read())


def rows_from_feed(content: bytes, now: datetime) -> list[dict[str, str]]:
    """Every open quote of the tracked matches; raises ValueError on an unexpected payload."""
    payload = json.loads(content)
    if not isinstance(payload, dict) or not payload.get("isSuccess"):
        raise ValueError("iddaa yanıtı başarısız veya beklenmeyen biçimde")
    start, end = now.timestamp(), (now + WINDOW).timestamp()
    out: list[dict[str, str]] = []
    for e in payload.get("data", {}).get("events", []):
        if not isinstance(e, dict) or e.get("sid") != 1 or e.get("ci") not in COMPETITIONS:
            continue
        if not e.get("hn") or not e.get("an") or not isinstance(e.get("d"), int) or not start < e["d"] <= end:
            continue
        for m in e.get("m") or []:
            if not isinstance(m, dict) or m.get("st") not in SUBTYPES or m.get("s") != 1:
                continue
            mbs = m.get("mbc", e.get("mbc"))
            for o in m.get("o") or []:
                odd = o.get("odd") if isinstance(o, dict) else None
                if not isinstance(odd, int | float) or not o.get("n"):
                    continue
                out.append({"e": str(e.get("i") or 0), "c": str(e["ci"]), "d": str(e["d"]), "h": str(e["hn"]).strip(),
                            "a": str(e["an"]).strip(), "st": str(m["st"]), "sov": str(m.get("sov") or ""),
                            "mbs": str(mbs) if isinstance(mbs, int) else "", "n": str(o["n"]).strip(),
                            "odd": f"{float(odd):g}"})
    return out


def _key(r: dict[str, str]) -> Key:
    return r["e"], r["st"], r["sov"], r["n"]


def read_file(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def day_state(day_dir: Path) -> dict[Key, tuple[str, str]]:
    """Latest (odds, mbs) of every quote written so far today, replaying the day's files in order."""
    state: dict[Key, tuple[str, str]] = {}
    index = day_dir / INDEX
    if not index.exists():
        return state
    for name in index.read_text(encoding="utf-8").split():
        path = day_dir / name
        if path.exists():
            for r in read_file(path):
                state[_key(r)] = (r["odd"], r["mbs"])
    return state


def changed(rows: list[dict[str, str]], state: dict[Key, tuple[str, str]]) -> list[dict[str, str]]:
    return [r for r in rows if state.get(_key(r)) != (r["odd"], r["mbs"])]


def write_snapshot(root: Path, rows: list[dict[str, str]], now: datetime) -> Path | None:
    """Write the changed rows of this run; None when nothing changed (no file, no commit)."""
    day_dir = root / f"{now:%Y-%m-%d}"
    new = changed(rows, day_state(day_dir))
    if not new:
        return None
    day_dir.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(new)
    path = day_dir / f"{now:%H%M%S}.csv.gz"
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(buf.getvalue().encode("utf-8"))
    index = day_dir / INDEX
    names = index.read_text(encoding="utf-8").split() if index.exists() else []
    index.write_text("\n".join([*names, path.name]) + "\n", encoding="utf-8")
    return path


def prune(root: Path, now: datetime) -> list[str]:
    cutoff = f"{now - timedelta(days=KEEP_DAYS):%Y-%m-%d}"
    gone = [d for d in root.iterdir() if d.is_dir() and d.name < cutoff] if root.exists() else []
    for d in gone:
        shutil.rmtree(d)
    return [d.name for d in gone]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/iddaa")
    ap.add_argument("--input", help="bulletin JSON file instead of the live address (tests)")
    ap.add_argument("--now", help="UTC time, ISO format (tests)")
    args = ap.parse_args(argv)
    now = datetime.fromisoformat(args.now).replace(tzinfo=UTC) if args.now else datetime.now(UTC)
    root = Path(args.root)
    try:
        content = Path(args.input).read_bytes() if args.input else fetch()
        rows = rows_from_feed(content, now)
    except (OSError, ValueError) as exc:  # urllib errors are OSError subclasses
        print(f"iddaa bülteni okunamadı: {exc}", file=sys.stderr)
        return 1
    path = write_snapshot(root, rows, now)
    pruned = prune(root, now)
    print(f"{len(rows)} oran okundu; " + (f"{path} yazıldı" if path else "değişen oran yok")
          + (f"; silinen eski klasörler: {pruned}" if pruned else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
