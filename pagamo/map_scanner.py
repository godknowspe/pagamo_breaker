"""
Finds valid attack/expansion targets by flood-filling outward from your own
territory to its border, using the batch /map/hexagons API.

/map/hexagons returns all hexes in a rectangular region in one request,
grouped by owner. One batch call replaces hundreds of individual hexagon_info
calls and avoids throttling entirely.

Response format (discovered by reverse-engineering):
  data = list of groups, each group = [header, entries]
  header[0]:  0            → empty/unowned hexes
              "<encoded>"  → gc encoded id (one group per owner present in the region)
  header[1]:  owner's total territory size
  entries for gc==0:  each [x, y] is one empty hex
  entries for gc!=0:  run-length encoded by column:
    [x, y, dir, flag]   = anchor: owned hex at (x,y)
    ["", dir, flag]     = continuation: same column, next y (y+1), same owner
    (gaps between anchors = hexes belonging to other groups)

A local map memory (.territory_map.json) caches results so repeat scans
don't re-fetch known hexes. mark_captured() updates it after a win.

Usage:
  from pagamo.map_scanner import find_attack_target, mark_captured
  target = find_attack_target(session, -5121, -1450, own_gc_id=3389027)
  if target:
      ...  # attack
      mark_captured(*target)   # on victory
"""
import json
import os
import time
from collections import Counter, deque
from pathlib import Path

import httpx

_HEXAGON_INFO_URL = "https://www.pagamo.org/api/v2/map/hexagon_info"
_HEXAGONS_URL = "https://www.pagamo.org/map/hexagons"
_MAP_MEMORY_PATH = Path(os.getenv("TERRITORY_MAP_PATH", ".territory_map.json"))
_SCAN_DELAY = float(os.getenv("SCAN_DELAY", "0.15"))

# 8-connectivity covers the full hex neighbourhood (a superset is fine — non-adjacent
# "diagonal" hexes will just be classified and stop BFS expansion there).
_NEIGHBORS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]

# Session-level cache: our gc's encoded id string, discovered once per process.
_session_gc_encoded: str | None = None


# ---------------------------------------------------------------------------
# Individual hex API (fallback for hexes outside the batch region)
# ---------------------------------------------------------------------------

def get_hex_info(session: httpx.Client, x: int, y: int, own_gc_id: int) -> dict | None:
    """Returns hex info dict from hexagon_info, or None on failure."""
    try:
        resp = session.post(_HEXAGON_INFO_URL, data={"x": x, "y": y, "gc_check": own_gc_id})
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "ok":
            return None
        return body.get("data")
    except Exception:
        return None


def _classify_hex_info(info: dict | None, own_gc_id: int) -> str | None:
    if info is None:
        return None
    owner = info.get("owner_gc_id")
    if owner == own_gc_id:
        return "mine"
    if info.get("cant_fight_status") is not None or info.get("protection_expire_time") is not None:
        return "blocked"
    return "enemy" if owner else "empty"


def _is_attackable(info: dict, own_gc_id: int) -> bool:
    """Used by callers that still have a raw hexagon_info dict."""
    if info.get("owner_gc_id") == own_gc_id:
        return False
    if info.get("cant_fight_status") is not None:
        return False
    if info.get("protection_expire_time") is not None:
        return False
    return True


# ---------------------------------------------------------------------------
# Batch hex API
# ---------------------------------------------------------------------------

def _fetch_batch(
    session: httpx.Client,
    x_min: int, x_max: int,
    y_min: int, y_max: int,
    own_gc_id: int,
) -> dict | None:
    """Call /map/hexagons for a rectangular region. Returns raw response body or None."""
    data: dict = {}
    for i, x in enumerate(range(x_min, x_max + 1)):
        data[f"col_array[{i}][x]"] = x
        data[f"col_array[{i}][y1]"] = y_min
        data[f"col_array[{i}][y2]"] = y_max
    data["gc_check"] = own_gc_id
    try:
        resp = session.post(_HEXAGONS_URL, data=data)
        resp.raise_for_status()
        body = resp.json()
        return body if body.get("status") == "ok" else None
    except Exception:
        return None


def _decode_batch(body: dict, my_gc_encoded: str | None) -> dict[tuple, str]:
    """
    Parse a /map/hexagons response body into {(x, y): status}.
    status ∈ "mine" | "empty" | "enemy"
    """
    result: dict = {}
    for group in body.get("data", []):
        header, entries = group[0], group[1]
        gc_enc = header[0]

        if gc_enc == 0:
            # Empty/unowned hexes — each entry is [x, y]
            for entry in entries:
                if entry and entry[0] != "":
                    result[(entry[0], entry[1])] = "empty"
        else:
            status = "mine" if (my_gc_encoded and str(gc_enc) == str(my_gc_encoded)) else "enemy"
            cur_x: int | None = None
            cur_y: int | None = None
            for entry in entries:
                if not entry:
                    continue
                if entry[0] != "":
                    # Anchor — new column position
                    cur_x, cur_y = entry[0], entry[1]
                    result[(cur_x, cur_y)] = status
                elif cur_y is not None:
                    # Continuation — same column, next row
                    cur_y += 1
                    result[(cur_x, cur_y)] = status

    return result


def _ensure_gc_encoded(
    session: httpx.Client,
    home_x: int, home_y: int,
    own_gc_id: int,
    mem: dict,
) -> str | None:
    """
    Discover which encoded gc string the server uses for own_gc_id.
    Probes the home hex (guaranteed mine) and looks for its group.
    Result is cached in-process and in the territory map.
    """
    global _session_gc_encoded
    if _session_gc_encoded:
        return _session_gc_encoded
    enc = mem.get("__gc_enc__")
    if enc:
        _session_gc_encoded = enc
        return enc

    body = _fetch_batch(session, home_x, home_x, home_y, home_y, own_gc_id)
    if body:
        for group in body.get("data", []):
            header, entries = group[0], group[1]
            gc_enc = header[0]
            if gc_enc == 0:
                continue
            for entry in entries:
                if entry and entry[0] != "" and entry[0] == home_x and len(entry) >= 2 and entry[1] == home_y:
                    _session_gc_encoded = str(gc_enc)
                    mem["__gc_enc__"] = _session_gc_encoded
                    print(f"[scan] gc encoding discovered: {_session_gc_encoded}")
                    return _session_gc_encoded

    print("[scan] Warning: could not discover gc encoding — home hex not found in batch response")
    return None


# ---------------------------------------------------------------------------
# Local map memory
# ---------------------------------------------------------------------------

def _key(x: int, y: int) -> str:
    return f"{x},{y}"


def _load_map() -> dict:
    try:
        return json.loads(_MAP_MEMORY_PATH.read_text())
    except Exception:
        return {}


def _save_map(mem: dict) -> None:
    try:
        _MAP_MEMORY_PATH.write_text(json.dumps(mem))
    except Exception:
        pass


def mark_captured(x: int, y: int) -> None:
    """Record a hex as now-owned so future scans expand past it."""
    mem = _load_map()
    mem[_key(x, y)] = "mine"
    _save_map(mem)


def forget_map() -> None:
    """Drop local map memory (e.g. after losing territory to force a full re-scan)."""
    global _session_gc_encoded
    _session_gc_encoded = None
    try:
        _MAP_MEMORY_PATH.unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Frontier search
# ---------------------------------------------------------------------------

def find_attack_target(
    session: httpx.Client,
    center_x: int,
    center_y: int,
    own_gc_id: int,
    radius: int = 30,
    exclude: set | None = None,
) -> tuple[int, int] | None:
    """
    Flood-fills through your territory and returns the first attackable frontier hex.

    Uses a single batch /map/hexagons call to populate the local map memory for the
    radius region — replacing hundreds of individual hexagon_info calls. Subsequent
    scans reuse cached memory; only newly-reached hexes outside the cached region
    need individual probes.

    radius: extent of the batch fetch and BFS depth cap.
    exclude: (x, y) tuples to skip as targets (e.g. hexes that already failed).
    """
    exclude = exclude or set()
    mem = _load_map()

    # Discover our gc encoded id (once per session)
    my_enc = _ensure_gc_encoded(session, center_x, center_y, own_gc_id, mem)

    # Batch-fetch the region when memory is sparse (first run or after forget_map)
    known_mine = sum(1 for k, v in mem.items() if not k.startswith("__") and v == "mine")
    if known_mine < 3:
        print(f"[scan] Batch-scanning ±{radius} region around ({center_x},{center_y})...")
        body = _fetch_batch(
            session,
            center_x - radius, center_x + radius,
            center_y - radius, center_y + radius,
            own_gc_id,
        )
        if body:
            hexes = _decode_batch(body, my_enc)
            for (x, y), status in hexes.items():
                mem[_key(x, y)] = status
            _save_map(mem)
            counts = Counter(v for v in hexes.values())
            print(f"[scan] Mapped {len(hexes)} hexes: {dict(counts)}")
        else:
            print("[scan] Batch fetch failed — falling back to individual probes")

    total_mine = sum(1 for k, v in mem.items() if not k.startswith("__") and v == "mine")
    print(f"[scan] Flood-fill from ({center_x},{center_y})  "
          f"({total_mine} mine hexes in memory)...")

    visited: set = set()
    queue: deque = deque([(center_x, center_y, 0)])
    checked = 0
    probed = 0

    while queue:
        x, y, dist = queue.popleft()
        if (x, y) in visited or dist > radius:
            continue
        visited.add((x, y))
        checked += 1

        status = mem.get(_key(x, y))
        if status is None:
            # Outside the batch region — probe individually
            info = get_hex_info(session, x, y, own_gc_id)
            status = _classify_hex_info(info, own_gc_id)
            probed += 1
            time.sleep(_SCAN_DELAY)
            if status:
                mem[_key(x, y)] = status

        if status == "mine":
            for dx, dy in _NEIGHBORS:
                nb = (x + dx, y + dy)
                if nb not in visited:
                    queue.append((nb[0], nb[1], dist + 1))
        elif status in ("empty", "enemy") and (x, y) not in exclude:
            _save_map(mem)
            label = "enemy" if status == "enemy" else "empty hex"
            print(f"[scan] Frontier: {label} at ({x},{y})  "
                  f"[{checked} checked, {probed} probed]")
            return x, y
        # "blocked" / None / excluded → dead end, don't expand

    _save_map(mem)
    print(f"[scan] No attackable frontier reachable "
          f"({checked} checked, {probed} probed)")
    return None
