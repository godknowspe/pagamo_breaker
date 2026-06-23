"""
Map battle automation.

Usage:
  from pagamo.map_battle import run_battle
  run_battle(session, hex_x=-5121, hex_y=-1450, target_gc_decoded_id=3389027)
"""
import time
from pagamo import graphql_client as gql
from pagamo import question as Q
from llm import solver

_ROOM_EXPIRE_SECONDS = 200   # max wait if room is busy and give-up fails
_QUOTA_REGEN_RATE = 10.0     # quota per minute (600/hr from probe data)
_QUOTA_PER_BATTLE = 30.0     # approximate cost per battle


def run_battle(
    session,
    hex_x: int,
    hex_y: int,
    target_gc_decoded_id: int,
    battle_type: str = "attack",
    answer_delay: float = 1.5,
) -> bool:
    """
    Runs a complete battle. Returns True if won, False if lost.
    answer_delay: seconds to wait before submitting (looks more human).
    """
    print(f"\n[battle] Starting {battle_type} on ({hex_x},{hex_y}) gc={target_gc_decoded_id}")

    # Start battle with automatic recovery for known transient errors
    while True:
        try:
            questions = gql.start_battle(session, hex_x, hex_y, target_gc_decoded_id, battle_type)
            break
        except gql.RoomBusyError:
            print("[battle] Still in a room — trying to give up...")
            if gql.give_up(session, hex_x, hex_y, target_gc_decoded_id, battle_type):
                time.sleep(2)
            else:
                print(f"[battle] Give up failed. Waiting {_ROOM_EXPIRE_SECONDS}s for room to expire...")
                time.sleep(_ROOM_EXPIRE_SECONDS)
        except gql.QuotaError:
            wait_min = _QUOTA_PER_BATTLE / _QUOTA_REGEN_RATE
            wait_sec = int(wait_min * 60) + 5
            print(f"[battle] Quota insufficient. Waiting {wait_sec}s (~{wait_min:.1f} min) to regenerate...")
            for remaining in range(wait_sec, 0, -10):
                print(f"  {remaining}s remaining...", end="\r", flush=True)
                time.sleep(min(10, remaining))
            print()

    print(f"[battle] {len(questions)} question(s) received")

    victory = None
    t_start = 0.0
    for i, raw_q in enumerate(questions, 1):
        pq = Q.parse(raw_q)
        print(f"\n[Q{i}] {Q.display(pq)}")

        if pq["type"] in ("fillin", "unknown"):
            print("  → skipping (type not supported)")
            answer = [""]
            cost_time = 3
        else:
            t_start = time.time()
            answer = solver.solve(pq)
            cost_time = max(1, int(time.time() - t_start))
            print(f"  → LLM answer: {answer}  (solved in {cost_time}s)")

            # Add delay to look more human
            elapsed = time.time() - t_start
            if elapsed < answer_delay:
                time.sleep(answer_delay - elapsed)

        result = gql.submit_answer(
            session,
            target_gc_decoded_id=target_gc_decoded_id,
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

    return bool(victory)
