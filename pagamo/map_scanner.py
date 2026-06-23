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
    if not info.get("owner_gc_id"):
        return False
    return True


def find_attack_target(
    session: httpx.Client,
    center_x: int,
    center_y: int,
    own_gc_id: int,
    radius: int = 5,
) -> tuple[int, int] | None:
    """
    Scans hexes around (center_x, center_y) in a spiral to find an attackable enemy hex.
    Returns (hex_x, hex_y) or None if no target found within radius.

    'Attackable' means: owned by someone else, no protection, cant_fight_status is null.
    The caller should pass own_gc_id as targetGcDecodedId when starting the battle.
    """
    print(f"[scan] Scanning radius {radius} around ({center_x},{center_y})...")
    checked = 0

    for r in range(1, radius + 1):
        candidates = []
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if abs(dx) == r or abs(dy) == r:
                    candidates.append((center_x + dx, center_y + dy))

        for x, y in candidates:
            info = get_hex_info(session, x, y, own_gc_id)
            checked += 1
            if info is None:
                continue
            if _is_attackable(info, own_gc_id):
                nick = info.get("owner_nickname", "?")
                gc = info.get("owner_gc_id")
                print(f"[scan] Found target at ({x},{y}) — {nick} (gc={gc})  [{checked} hexes checked]")
                return x, y

    print(f"[scan] No target found after checking {checked} hexes")
    return None
