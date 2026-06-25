"""
Scans nearby hexes to find valid enemy targets for attack.

Usage:
  from pagamo.map_scanner import find_attack_target
  result = find_attack_target(session, center_x=-5121, center_y=-1450, own_gc_id=3389027)
  if result:
      hex_x, hex_y = result
"""
import httpx

_HEXAGON_INFO_URL = "https://www.pagamo.org/api/v2/map/hexagon_info"


def get_hex_info(session: httpx.Client, x: int, y: int, own_gc_id: int) -> dict | None:
    """Returns hex info dict, or None if hex doesn't exist or request fails."""
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


_EMPTY_RING_STREAK_STOP = 2   # consecutive non-existent rings → off the map, stop


def find_attack_target(
    session: httpx.Client,
    center_x: int,
    center_y: int,
    own_gc_id: int,
    radius: int = 30,
    exclude: set | None = None,
) -> tuple[int, int] | None:
    """
    Expands outward ring-by-ring from (center_x, center_y) to find the frontier of
    your territory and the first attackable hex beyond it.

    Unlike a fixed-radius scan, this walks straight through contiguous own territory
    (which is never attackable) until it reaches the border and finds an empty or
    enemy hex. It stops early once it crosses the frontier and hits empty space, so a
    large own territory no longer hides the border behind a small radius.

    radius: a safety cap on how far to expand (rings). Returns (hex_x, hex_y) or None.
    'Attackable' means: owned by someone else (or unowned), no protection, cant_fight.
    exclude: a set of (x, y) tuples to skip (e.g. hexes that already failed).
    """
    exclude = exclude or set()
    print(f"[scan] Expanding from ({center_x},{center_y}) to find territory border (max radius {radius})...")
    checked = 0
    own_seen = False          # have we passed through any of our own hexes yet?
    empty_streak = 0          # consecutive rings with no existing hexes at all

    for r in range(1, radius + 1):
        candidates = []
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if abs(dx) == r or abs(dy) == r:
                    candidates.append((center_x + dx, center_y + dy))

        ring_has_existing = False
        for x, y in candidates:
            if (x, y) in exclude:
                continue
            info = get_hex_info(session, x, y, own_gc_id)
            checked += 1
            if info is None:
                continue
            ring_has_existing = True
            if info.get("owner_gc_id") == own_gc_id:
                own_seen = True
            elif _is_attackable(info, own_gc_id):
                gc = info.get("owner_gc_id")
                if gc:
                    nick = info.get("owner_nickname", "?")
                    print(f"[scan] Found enemy at ({x},{y}) — {nick} (gc={gc})  [ring {r}, {checked} hexes checked]")
                else:
                    print(f"[scan] Found empty hex at ({x},{y})  [ring {r}, {checked} hexes checked]")
                return x, y

        if ring_has_existing:
            empty_streak = 0
        else:
            empty_streak += 1
            # Once we've left our own territory and hit empty space, there's no
            # more map in range — stop instead of burning the rest of the radius.
            if own_seen and empty_streak >= _EMPTY_RING_STREAK_STOP:
                print(f"[scan] Crossed the territory border into empty space at ring {r} — no targets nearby.")
                break

    print(f"[scan] No target found after checking {checked} hexes (up to radius {radius})")
    return None
