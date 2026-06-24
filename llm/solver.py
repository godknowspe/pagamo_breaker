"""
LLM solver — takes a parsed question dict, returns answer in submitRoom format.

Return value is always list[str], e.g.:
  TrueOrFalse → ["O"] or ["X"]
  Choice      → ["A"]  (letter position)
"""
import os


def solve(pq: dict) -> list[str]:
    """
    pq: output of pagamo.question.parse()
    Returns answer array ready to pass to submitRoom.
    """
    if not pq["options"]:
        return [""]  # fillin / unknown — no automation yet

    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    raw = _solve_gemini(pq) if provider == "gemini" else _solve_anthropic(pq)
    return [raw]


def _build_prompt(pq: dict) -> str:
    opts = "\n".join(f"  {k}: {v}" for k, v in pq["options"].items())
    return (
        "以下是一道選擇題或是非題，請直接回答最正確的選項代號"
        "（是非題回答 O 或 X；選擇題回答選項字母，例如 A、B、C、D），"
        "不要解釋，只回答一個代號。\n\n"
        f"題目：{pq['text']}\n\n選項：\n{opts}\n\n答案："
    )


def _extract(text: str, options: dict) -> str:
    text = text.strip()
    # Try exact match first (e.g. "O", "X", "0")
    for k in options:
        if text.upper() == k.upper():
            return k
    # First character fallback
    for ch in text.upper():
        if ch in options:
            return ch
    return list(options.keys())[0]


def _solve_gemini(pq: dict) -> str:
    from google import genai
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Set GOOGLE_API_KEY in .env")
    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    response = client.models.generate_content(model=model, contents=_build_prompt(pq))
    return _extract(response.text, pq["options"])


def _solve_anthropic(pq: dict) -> str:
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("Set ANTHROPIC_API_KEY in .env")
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=4,
        messages=[{"role": "user", "content": _build_prompt(pq)}],
    )
    return _extract(msg.content[0].text, pq["options"])
