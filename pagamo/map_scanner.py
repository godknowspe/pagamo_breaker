"""
Finds valid attack/expansion targets by flood-filling outward from your own
territory to its border.

Instead of re-scanning a fixed square radius from a center each time (which
re-checks the whole interior and hides the border behind a large blob), this
walks the graph of your owned hexes outward and returns the first attackable
hex (empty or enemy) on the frontier.

A local map memory (.territory_map.json) records each hex's status so known
interior hexes are never re-queried — only unknown border hexes cost a request.
After you capture a hex, mark_captured() turns it into territory, so its
neighbours become the new frontier and the next scan naturally spirals outward.

Usage:
  from pagamo.map_scanner import find_attack_target, mark_captured
  result = find_attack_target(session, center_x=-5121, center_y=-1450, own_gc_id=3389027)
  if result:
      hex_x, hex_y = result
      ...  # attack
      mark_captured(hex_x, hex_y)   # on victory
"""
import json
import os
import time
from collections import deque
from pathlib import Path

import httpx

_HEXAGON_INFO_URL = "https://www.pagamo.org/api/v2/map/hexagon_info"

# Local persistent map memory and throttle guard (both overridable via env).
_MAP_MEMORY_PATH = Path(os.getenv("TERRITORY_MAP_PATH", ".territory_map.json"))
_SCAN_DELAY = float(os.getenv("SCAN_DELAY", "0.15"))   # seconds between hex probes

# 8-neighbourhood in clockwise order. We use the full neighbourhood (a superset
# of the true hex adjacency) so frontier discovery never misses a border hex;
# an over-eager target that isn't actually attackable is caught by the battle
# loop's error recovery, which excludes it and rescans.
_NEIGHBORS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]


def get_hex_info(session: httpx.Client, x: int, y: int, own_gc_id: int) -> dict | None:
    """Returns hex info dict, or None if hex doesn't exist or the request fails."""
    try:
        resp = session.post(_HEXAGON_INFO_URL, data={"x": x, "y": y, "gc_check": own_gc_id})
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "ok":
            return None
        return body.get("data")
    except Exception:
        return None


def _is_attackable(info: dict, own_gc_id: int) -> bool:
    if info.get("owner_gc_id") == own_gc_id:
        return False
    if info.get("cant_fight_status") is not None:
        return False
    if info.get("protection_expire_time") is not None:
        return False
    return True


# --- local map memory ------------------------------------------------------

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


def _classify(info: dict | None, own_gc_id: int) -> str | None:
    """Map a hexagon_info payload to a status string, or None if unknown/error."""
    if info is None:
        return None                       # request failed / throttled — don't cache
    owner = info.get("owner_gc_id")
    if owner == own_gc_id:
        return "mine"
    if info.get("cant_fight_status") is not None or info.get("protection_expire_time") is not None:
        return "blocked"                  # protected / can't-fight enemy: dead end
    if owner:
        return "enemy"
    return "empty"


def mark_captured(x: int, y: int) -> None:
    """Record a hex as now-owned so future scans expand past it."""
    mem = _load_map()
    mem[_key(x, y)] = "mine"
    _save_map(mem)


def forget_map() -> None:
    """Drop the local map memory (e.g. after losing territory)."""
    try:
        _MAP_MEMORY_PATH.unlink()
    except FileNotFoundError:
        pass


# --- frontier search -------------------------------------------------------

def find_attack_target(
    session: httpx.Client,
    center_x: int,
    center_y: int,
    own_gc_id: int,
    radius: int = 30,
    exclude: set | None = None,
) -> tuple[int, int] | None:
    """
    Flood-fills outward from (center_x, center_y) through your own territory and
    returns the first attackable hex (empty or enemy) on the border.

    Only your owned hexes are traversed; the search never expands through empty
    space or enemy/blocked hexes, so it touches just your interior plus the
    bordering frontier — not the whole map. Known hexes are read from local
    memory; only unknown ones cost a (throttle-delayed) request.

    radius: max flood-fill depth (rings) from the center, as a safety cap.
    exclude: (x, y) tuples to skip as targets (e.g. hexes that already failed).
    Returns (hex_x, hex_y) or None if no reachable frontier target exists.
    """
    exclude = exclude or set()
    mem = _load_map()
    visited: set = set()
    queue: deque = deque([(center_x, center_y, 0)])
    checked = 0          # hexes examined (memory or network)
    probed = 0           # hexes that needed a live request

    print(f"[scan] Flood-fill from ({center_x},{center_y}) to your territory border "
          f"(max {radius} rings, {len(mem)} hexes remembered)...")

    while queue:
        x, y, dist = queue.popleft()
        if (x, y) in visited or dist > radius:
            continue
        visited.add((x, y))
        checked += 1

        status = mem.get(_key(x, y))
        if status is None:
            info = get_hex_info(session, x, y, own_gc_id)
            status = _classify(info, own_gc_id)
            probed += 1
            time.sleep(_SCAN_DELAY)
            if status is not None:
                mem[_key(x, y)] = status

        if status == "mine":
            # Owned — expand the frontier through its neighbours.
            for dx, dy in _NEIGHBORS:
                nb = (x + dx, y + dy)
                if nb not in visited:
                    queue.append((nb[0], nb[1], dist + 1))
        elif status in ("empty", "enemy") and (x, y) not in exclude:
            _save_map(mem)
            if status == "enemy":
                print(f"[scan] Frontier target: enemy at ({x},{y})  "
                      f"[{checked} hexes checked, {probed} probed]")
            else:
                print(f"[scan] Frontier target: empty hex at ({x},{y})  "
                      f"[{checked} hexes checked, {probed} probed]")
            return x, y
        # "blocked" / unknown-error / excluded → dead end, don't expand through it.

    _save_map(mem)
    print(f"[scan] No attackable frontier reachable ({checked} hexes checked, {probed} probed). "
          f"Either every border hex is protected/tried, or your start hex isn't yours.")
    return None
