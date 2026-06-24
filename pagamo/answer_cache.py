"""
Persistent answer cache keyed by numeric questionId.

PaGamO's /rooms/get_detailed_answer only returns the correct answer when you are
NOT in an answering room (it's the post-battle "view explanation" feature, and is
blocked in-room with "should not in room"). So we can't peek before submitting.

Instead we learn: after a battle ends we fetch the official answer for each
questionId and store it here. Question banks repeat, so subsequent encounters with
the same questionId are answered for free and 100% correctly — no LLM, no RPM cost.
"""
import json
import os

_CACHE_PATH = os.getenv("ANSWER_CACHE_PATH", ".answer_cache.json")


def _load() -> dict:
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get(question_id) -> list[str] | None:
    """Return cached answer list for a questionId, or None if not cached."""
    if question_id is None:
        return None
    return _load().get(str(question_id))


def put(question_id, answer: list[str]) -> None:
    """Store an answer list for a questionId (no-op if either is falsy)."""
    if question_id is None or not answer:
        return
    cache = _load()
    cache[str(question_id)] = answer
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def size() -> int:
    return len(_load())
