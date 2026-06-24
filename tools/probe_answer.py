"""
Inspect the raw /rooms/get_detailed_answer response for given questionId(s).

IMPORTANT: this endpoint only returns the answer when you are NOT in an answering
room (it's blocked in-room with "should not in room"). So run this between
battles, passing questionIds you've already seen (e.g. from .answer_cache.json
keys or earlier battle logs). Handy for learning the Choice answer format.

Usage:
  python -m tools.probe_answer 2922058 3180677
"""
import json
import os
import sys

from dotenv import load_dotenv

from pagamo.auth import login
from pagamo import graphql_client as gql

load_dotenv()


def main():
    qids = sys.argv[1:]
    if not qids:
        print("Pass one or more questionIds, e.g. python -m tools.probe_answer 2922058")
        sys.exit(1)

    session = login(os.getenv("PAGAMO_ACCOUNT", ""), os.getenv("PAGAMO_PASSWORD", ""))

    for qid in qids:
        r = session.post(gql.DETAILED_ANSWER_URL, data={"id": qid})
        print(f"\n=== questionId={qid} (HTTP {r.status_code}) ===")
        try:
            body = r.json()
        except Exception:
            print(r.text[:500])
            continue
        if body.get("status") != "ok":
            print(f"  {body}")  # likely {"status":"error","data":"should not in room"}
            continue
        q = (body.get("data") or {}).get("question") or {}
        render = q.get("render_info") or {}
        print(f"  type        = {q.get('type')!r}")
        print(f"  answer_type = {q.get('answer_type')!r}")
        print(f"  answer      = {q.get('answer')!r}")
        print(f"  selections  = {(q.get('selections') or render.get('selections'))!r}")
        print(f"  show_detail = {q.get('show_detail')!r}")


if __name__ == "__main__":
    main()
