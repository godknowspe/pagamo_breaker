"""
GraphQL client for Pagamo map battle flow.

Battle sequence:
  1. answerOnMap(battleType, hexX, hexY, targetGcDecodedId)
       → returns room{questions:[...]}  (all questions for this battle)
  2. submitRoom(targetGcDecodedId, questionId, answer, costTime)
       → returns battleResult{victory, ...}
     Repeat step 2 for each question in the list.
"""
import time
import httpx

GRAPHQL_URL = "https://www.pagamo.org/graphql"
DETAILED_ANSWER_URL = "https://www.pagamo.org/rooms/get_detailed_answer"

_QUESTION_FIELDS = """
fragment QuestionFields on InterfaceQuestion {
  __isInterfaceQuestion: __typename
  id
  typeName
  questionId
  content
  ... on Choice {
    multipleAnswer
    selections { content position }
  }
  ... on TrueOrFalse { typeName }
  ... on FillIn { ansSlotCount }
}
"""

_ANSWER_ON_MAP = """
mutation AnswerOnMap($input: RoomAnswerOnMapInput!) {
  answerOnMap(input: $input) {
    gc {
      allowGiveUpAnswering
      quota
      room {
        battleType
        endTimestamp
        remainSeconds
        missionName
        questions {
          __typename
          ...QuestionFields
          id
        }
      }
      id
    }
    errors { code message }
  }
}
""" + _QUESTION_FIELDS

_SUBMIT_ROOM = """
mutation SubmitRoom($input: RoomSubmitInput!) {
  submitRoom(input: $input) {
    battleResult {
      battleType
      victory
      question { id questionId __typename }
      damageDetails { key value }
      gamecharacter { money hexagonOccupation id }
      easterEggsInfo {
        cantAnswerInfo { reason nextAnswerableTimestamp }
      }
    }
    errors { code message }
  }
}
"""

_GIVE_UP_QUESTION = """
mutation GiveUpQuestion($input: RoomSubmitInput!) {
  giveUpQuestion(input: $input) {
    errors { code message }
  }
}
"""


class RoomBusyError(Exception):
    """Raised when gc is still in an existing room."""

class QuotaError(Exception):
    """Raised when quota is insufficient to start a battle."""
    def __init__(self, errors, current_quota: float | None = None):
        super().__init__(errors)
        self.current_quota = current_quota  # None if server didn't return it

class OwnTerritoryError(Exception):
    """Raised when trying to attack own territory (error FQJ3BPMZ)."""

class NoQuestionsError(Exception):
    """Raised when the hex/mission has no answerable questions left (error 9PCK5KN6)."""


def _gql(session: httpx.Client, query: str, variables: dict) -> dict:
    resp = session.post(GRAPHQL_URL, json={"query": query, "variables": variables})
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"GraphQL error: {body['errors']}")
    return body["data"]


def give_up(
    session: httpx.Client,
    hex_x: int,
    hex_y: int,
    target_gc_decoded_id: int,
    battle_type: str = "attack",
) -> bool:
    """
    Rejoins the existing room to get question IDs, then gives up each question.
    Returns True if at least one giveUpQuestion call succeeded.
    """
    try:
        # Rejoin the existing room to retrieve its questions
        data = _gql(session, _ANSWER_ON_MAP, {
            "input": {
                "battleType": battle_type,
                "targetGcDecodedId": target_gc_decoded_id,
                "hexagonX": hex_x,
                "hexagonY": hex_y,
            },
        })
        gc = data["answerOnMap"].get("gc")
        room = gc.get("room") if gc else None
        if not room:
            # answerOnMap errored (e.g. GJ6MGRSJ) — no room payload to give up from
            return False
        questions = room.get("questions", [])
        if not questions:
            return False

        success = False
        for q in questions:
            qid = q.get("id")
            if not qid:
                continue
            try:
                _gql(session, _GIVE_UP_QUESTION, {
                    "input": {
                        "targetGcDecodedId": target_gc_decoded_id,
                        "questionId": qid,
                        "answer": [],
                        "costTime": 1,
                    }
                })
                print(f"[gql] Gave up question {qid[:20]}...")
                success = True
            except Exception as e:
                print(f"[gql] giveUpQuestion error: {e}")
        return success
    except Exception as e:
        print(f"[gql] give_up rejoin failed: {e}")
        return False


def start_battle(
    session: httpx.Client,
    hex_x: int,
    hex_y: int,
    target_gc_decoded_id: int,
    battle_type: str = "attack",
) -> list[dict]:
    """Starts a map battle. Returns list of raw question dicts."""
    data = _gql(session, _ANSWER_ON_MAP, {
        "input": {
            "battleType": battle_type,
            "targetGcDecodedId": target_gc_decoded_id,
            "hexagonX": hex_x,
            "hexagonY": hex_y,
        },
    })
    payload = data["answerOnMap"]
    errors = payload.get("errors", [])
    # quota may be returned even alongside errors (GraphQL partial data)
    current_quota: float | None = (payload.get("gc") or {}).get("quota")
    if current_quota is not None:
        print(f"[gql] Current quota: {current_quota:.1f}")
    if errors:
        codes = [e.get("code", "") for e in errors]
        if "GJ6MGRSJ" in codes:  # "Gc should not in room"
            raise RoomBusyError(errors)
        if "K3EF4FUQ" in codes:  # "Quota is not enough"
            raise QuotaError(errors, current_quota=current_quota)
        if "FQJ3BPMZ" in codes:  # "這是自己的領土"
            raise OwnTerritoryError(errors)
        if "9PCK5KN6" in codes:  # "No available question to answer"
            raise NoQuestionsError(errors)
        raise RuntimeError(f"Battle start error: {errors}")
    gc = payload["gc"]
    return gc["room"]["questions"]


def submit_answer(
    session: httpx.Client,
    target_gc_decoded_id: int,
    question_id: str,
    answer: list[str],
    cost_time: int = 3,
) -> dict:
    """Submits one answer. Returns battleResult dict."""
    data = _gql(session, _SUBMIT_ROOM, {
        "input": {
            "targetGcDecodedId": target_gc_decoded_id,
            "questionId": question_id,
            "answer": answer,
            "costTime": cost_time,
        }
    })
    errors = data["submitRoom"].get("errors", [])
    if errors:
        raise RuntimeError(f"Submit error: {errors}")
    return data["submitRoom"]["battleResult"]


def get_detailed_answer(session: httpx.Client, question_id) -> dict | None:
    """
    Fetches the correct answer for a question via /rooms/get_detailed_answer.

    NOTE: this only works when NOT in an answering room — the server blocks it
    in-room with {"status":"error","data":"should not in room"}. Call it after a
    battle ends. Returns the `question` dict (with 'answer', 'selections', 'type',
    nested render_info) or None if unavailable / answer hidden / still in room.
    """
    if not question_id:
        return None
    try:
        resp = session.post(DETAILED_ANSWER_URL, data={"id": question_id})
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "ok":
            return None  # e.g. "should not in room"
        q = (body.get("data") or {}).get("question")
        # answer lives at the top level of the question object when exposed
        if not q or q.get("answer") in (None, ""):
            return None
        # flatten render_info fields (selections, show_answer) for convenience
        render = q.get("render_info") or {}
        if "selections" not in q and "selections" in render:
            q["selections"] = render["selections"]
        return q
    except Exception:
        return None
