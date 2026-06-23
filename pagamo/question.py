"""
Parse raw GraphQL question dicts into clean format for LLM solving.

Answer format per type (matches what submitRoom expects):
  TrueOrFalse → ["O"] (是) or ["X"] (否)
  Choice      → [str(position)]  e.g. ["0"], ["2"]
  FillIn      → [text]  (not yet automated)
"""
from html.parser import HTMLParser


class _StripHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(p.strip() for p in self._parts if p.strip())


def strip_html(html: str) -> str:
    p = _StripHTML()
    p.feed(html)
    return p.get_text()


def parse(q: dict) -> dict:
    """
    Returns:
      type    : "trueorfalse" | "choice" | "fillin" | "unknown"
      text    : plain-text question
      options : {answer_value: display_text}
                TrueOrFalse → {"O": "是 (True)", "X": "否 (False)"}
                Choice      → {"0": "...", "1": "...", ...}
      id      : GraphQL decoded id (used in submitRoom)
    """
    type_name = (q.get("typeName") or q.get("__typename") or "").lower()
    text = strip_html(q.get("content", ""))
    qid = q.get("id", "")
    num_id = q.get("questionId")  # numeric id used by /rooms/get_detailed_answer

    if "trueorfalse" in type_name:
        return {
            "type": "trueorfalse",
            "text": text,
            "options": {"O": "是 (True)", "X": "否 (False)"},
            "id": qid,
            "questionId": num_id,
        }

    if "choice" in type_name:
        options = {
            str(sel["position"]): strip_html(sel["content"])
            for sel in q.get("selections", [])
        }
        return {"type": "choice", "text": text, "options": options,
                "id": qid, "questionId": num_id}

    if "fillin" in type_name:
        return {"type": "fillin", "text": text, "options": {},
                "id": qid, "questionId": num_id}

    return {"type": "unknown", "text": text, "options": {},
            "id": qid, "questionId": num_id}


def answer_from_detailed(pq: dict, detail: dict) -> list[str] | None:
    """
    Convert a /rooms/get_detailed_answer payload into submitRoom format,
    matching the same scheme parse() / solver use.

    Returns the answer list (e.g. ["O"], ["2"]) or None if it can't be mapped
    (caller should fall back to the LLM).
    """
    raw = detail.get("answer")
    if raw is None or raw == "":
        return None

    # answer may be a single value or a list (multiple-answer choice)
    raw_list = raw if isinstance(raw, list) else [raw]
    raw_list = [str(a).strip() for a in raw_list if str(a).strip() != ""]
    if not raw_list:
        return None

    if pq["type"] == "trueorfalse":
        # answer is already "O" / "X"
        return [raw_list[0].upper()]

    if pq["type"] == "choice":
        selections = detail.get("selections") or []
        out: list[str] = []
        for a in raw_list:
            if a.isdigit() and a in pq["options"]:
                out.append(a)                       # already a position
            elif a in selections:
                out.append(str(selections.index(a)))  # match by content order
            else:
                # try matching against parsed option text
                match = next((k for k, v in pq["options"].items()
                              if v == strip_html(a)), None)
                if match is None:
                    return None
                out.append(match)
        return out or None

    # fillin / unknown — not handled here
    return None


def display(pq: dict) -> str:
    lines = [f"[{pq['type'].upper()}] {pq['text']}"]
    for k, v in pq["options"].items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)
