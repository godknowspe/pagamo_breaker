"""
Map battle automation.

Usage:
  from pagamo.map_battle import run_battle
  run_battle(session, hex_x=-5121, hex_y=-1450, own_gc_id=3389027)
  run_battle(session, hex_x=-5121, hex_y=-1450, own_gc_id=3389027, auto_scan=True)
"""
import random
import time
from pagamo import graphql_client as gql
from pagamo import question as Q
from pagamo import map_scanner
from pagamo import answer_cache
from llm import solver

_ROOM_EXPIRE_SECONDS = 200   # max wait if room is busy and give-up fails
_QUOTA_REGEN_RATE = 10.0     # quota per minute (600/hr from probe data)
_QUOTA_PER_BATTLE = 30.0     # approximate cost per battle
_QUOTA_JITTER = 20           # ±seconds of random jitter added to every wait


def _quota_wait_seconds(current_quota: float | None) -> int:
    if current_quota is not None:
        deficit = max(0.0, _QUOTA_PER_BATTLE - current_quota)
        base = int(deficit / _QUOTA_REGEN_RATE * 60) + 10
        print(f"[battle]   current quota={current_quota:.1f}, deficit={deficit:.1f}, base wait={base}s")
    else:
        base = int(_QUOTA_PER_BATTLE / _QUOTA_REGEN_RATE * 60) + 10
    jitter = random.randint(-_QUOTA_JITTER // 2, _QUOTA_JITTER)
    return max(30, base + jitter)


def run_battle(
    session,
    hex_x: int,
    hex_y: int,
    own_gc_id: int,
    battle_type: str = "attack",
    answer_delay: float = 1.5,
    auto_scan: bool = False,
    scan_radius: int = 5,
    use_cache: bool = True,
) -> bool:
    """
    Runs a complete battle. Returns True if won, False if lost.

    own_gc_id: the player's own gc_id (used as targetGcDecodedId in the API).
    auto_scan: if True, automatically scan nearby hexes when own territory is hit.
    answer_delay: seconds to wait before submitting (looks more human).
    use_cache: if True, answer from the learned cache when a questionId repeats,
               and after each battle fetch official answers (out-of-room) to grow it.
    """
    cur_x, cur_y = hex_x, hex_y
    print(f"\n[battle] Starting {battle_type} on ({cur_x},{cur_y}) gc={own_gc_id}  (answer_delay={answer_delay}s)")

    # Start battle with automatic recovery for known transient errors
    while True:
        try:
            questions = gql.start_battle(session, cur_x, cur_y, own_gc_id, battle_type)
            break
        except gql.RoomBusyError:
            print("[battle] Still in a room — trying to give up...")
            if gql.give_up(session, cur_x, cur_y, own_gc_id, battle_type):
                time.sleep(2)
            else:
                print(f"[battle] Give up failed. Waiting {_ROOM_EXPIRE_SECONDS}s for room to expire...")
                time.sleep(_ROOM_EXPIRE_SECONDS)
        except gql.QuotaError as e:
            wait_sec = _quota_wait_seconds(e.current_quota)
            print(f"[battle] Quota insufficient. Waiting {wait_sec}s to regenerate...")
            for remaining in range(wait_sec, 0, -10):
                print(f"  {remaining}s remaining...", end="\r", flush=True)
                time.sleep(min(10, remaining))
            print()
        except gql.OwnTerritoryError:
            if not auto_scan or battle_type != "attack":
                print("[battle] Target is own territory. Use --auto to scan for enemy hexes.")
                return False
            print("[battle] Target is own territory — scanning for enemy hexes...")
            result = map_scanner.find_attack_target(session, cur_x, cur_y, own_gc_id, scan_radius)
            if result is None:
                print("[battle] No enemy hex found nearby. Expand radius or move to a new area.")
                return False
            cur_x, cur_y = result
            print(f"[battle] New target: ({cur_x},{cur_y})")

    print(f"[battle] {len(questions)} question(s) received")

    victory = None
    t_start = 0.0
    parsed = [Q.parse(raw_q) for raw_q in questions]
    for i, pq in enumerate(parsed, 1):
        print(f"\n[Q{i}] {Q.display(pq)}")

        if pq["type"] in ("fillin", "unknown"):
            print("  → skipping (type not supported)")
            answer = [""]
            cost_time = 3
        else:
            t_start = time.time()

            # 1. Cache hit — official answer learned from a previous battle (free, 100%)
            answer = None
            if use_cache:
                answer = answer_cache.get(pq.get("questionId"))
                if answer:
                    print(f"  → Cached answer: {answer}")

            # 2. Fall back to the LLM for first-time questions
            if not answer:
                answer = solver.solve(pq)
                print(f"  → LLM answer: {answer}")

            cost_time = max(1, int(time.time() - t_start))

            # Add delay to look more human (with slight jitter)
            target = answer_delay + random.uniform(-0.5, 1.5)
            elapsed = time.time() - t_start
            if elapsed < target:
                time.sleep(target - elapsed)

        result = gql.submit_answer(
            session,
            target_gc_decoded_id=own_gc_id,
            question_id=pq["id"],
            answer=answer,
            cost_time=cost_time,
        )
        victory = result.get("victory")
        print(f"  → Result: {'WIN ✓' if victory else 'LOSE ✗'}")

        cantAnswer = (result.get("easterEggsInfo") or {}).get("cantAnswerInfo")
        if cantAnswer:
            print(f"  ⚠ Can't answer: {cantAnswer.get('reason')}")
            break

    # Room is over now — learn official answers for next time (only works out-of-room)
    if use_cache:
        _learn_answers(session, parsed)

    return bool(victory)


def _learn_answers(session, parsed: list[dict]) -> None:
    """After a battle ends, fetch the official answer for each question and cache it."""
    learned = 0
    for pq in parsed:
        qid = pq.get("questionId")
        if qid is None or answer_cache.get(qid) is not None:
            continue
        detail = gql.get_detailed_answer(session, qid)
        if not detail:
            continue
        ans = Q.answer_from_detailed(pq, detail)
        if ans:
            answer_cache.put(qid, ans)
            learned += 1
    if learned:
        print(f"[cache] Learned {learned} official answer(s) (total cached: {answer_cache.size()})")
