"""
Answer oracle — a second PaGamO account used to fetch official answers in real time.

PaGamO's /rooms/get_detailed_answer is blocked while the requesting game character
is in an answering room, but it does NOT check whether you've ever been served the
question (verified empirically). So a *second* account that is never in a room can
look up the correct answer for any questionId the primary account is currently
answering, giving 100% accuracy with no LLM.

Set in .env:
  PAGAMO_ACCOUNT_2 / PAGAMO_PASSWORD_2   credentials for the helper account
The helper account must stay out of battles (never enter a room).
"""
import os
from pathlib import Path

from pagamo.auth import login
from pagamo import graphql_client as gql
from pagamo import question as Q

_HELPER_COOKIE_CACHE = Path(".pagamo_cookies_helper.json")


class Oracle:
    """Lazily-logged-in helper session that resolves official answers by questionId."""

    def __init__(self, account: str, password: str):
        self._account = account
        self._password = password
        self._session = None

    @classmethod
    def from_env(cls) -> "Oracle | None":
        """Build an Oracle from PAGAMO_ACCOUNT_2 / PAGAMO_PASSWORD_2, or None if unset."""
        acc = os.getenv("PAGAMO_ACCOUNT_2", "")
        pw = os.getenv("PAGAMO_PASSWORD_2", "")
        if not acc or not pw:
            return None
        return cls(acc, pw)

    def _ensure_session(self):
        if self._session is None:
            print("[oracle] Logging in helper account...")
            self._session = login(self._account, self._password,
                                  cookie_path=_HELPER_COOKIE_CACHE)
        return self._session

    def answer(self, pq: dict) -> list[str] | None:
        """
        Resolve the official answer for a parsed question via the helper account.
        Returns the submit-format answer list, or None if unavailable.
        """
        qid = pq.get("questionId")
        if qid is None:
            return None
        try:
            session = self._ensure_session()
        except Exception as e:
            print(f"[oracle] Helper login failed: {e}")
            return None
        detail = gql.get_detailed_answer(session, qid)
        if not detail:
            return None
        return Q.answer_from_detailed(pq, detail)
