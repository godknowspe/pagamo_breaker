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

    if "trueorfalse" in type_name:
        return {
            "type": "trueorfalse",
            "text": text,
            "options": {"O": "是 (True)", "X": "否 (False)"},
            "id": qid,
        }

    if "choice" in type_name:
        options = {
            str(sel["position"]): strip_html(sel["content"])
            for sel in q.get("selections", [])
        }
        return {"type": "choice", "text": text, "options": options, "id": qid}

    if "fillin" in type_name:
        return {"type": "fillin", "text": text, "options": {}, "id": qid}

    return {"type": "unknown", "text": text, "options": {}, "id": qid}


def display(pq: dict) -> str:
    lines = [f"[{pq['type'].upper()}] {pq['text']}"]
    for k, v in pq["options"].items():
        lines.append(f"  {k}: {v}")
    return "\n".join(lines)
