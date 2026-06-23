"""
Pagamo network + DOM probe tool.

Opens a real browser (non-headless) so you can log in and navigate manually.
Automatically captures:
  - All XHR / Fetch requests & responses
  - WebSocket frames (sent and received)

Interactive commands (type in terminal while browser is open):
  dom     → dump question-related DOM structure of current page (+ any iframes)
  sel     → test all selectors from pagamo/selectors.py and report which ones match
  ws      → print captured WebSocket messages so far
  net     → print captured network requests so far
  save    → save everything to probe_output.json
  quit    → close browser and exit

Usage:
  .venv/bin/python tools/probe.py
"""
import asyncio
import json
import sys
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from pagamo import selectors as SEL

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, Frame

load_dotenv()

_ws_log: list[dict] = []
_net_log: list[dict] = []


async def _dump_dom(page: Page) -> str:
    lines = []

    async def scan_frame(frame: Frame, label: str):
        url = frame.url
        lines.append(f"\n=== Frame: {label} ({url}) ===")
        # Question text
        try:
            el = frame.locator(SEL.QUESTION_TEXT).first
            txt = await el.inner_text(timeout=2000)
            lines.append(f"  QUESTION: {txt[:200]}")
        except Exception:
            lines.append(f"  QUESTION selector: no match")

        # Options
        try:
            containers = frame.locator(SEL.OPTION_CONTAINER)
            n = await containers.count()
            lines.append(f"  OPTIONS ({n} found):")
            for i in range(n):
                c = containers.nth(i)
                try:
                    letter = await c.locator(SEL.OPTION_LETTER).inner_text(timeout=1000)
                    text = await c.locator(SEL.OPTION_TEXT).inner_text(timeout=1000)
                    correct = await c.get_attribute("data-correct") or ""
                    lines.append(f"    {letter}. {text[:80]}  data-correct={correct!r}")
                except Exception as e:
                    lines.append(f"    [{i}] error: {e}")
        except Exception:
            lines.append(f"  OPTIONS selector: no match")

        # Raw HTML snippet around pgo-style classes
        try:
            snippet = await frame.evaluate("""() => {
                const els = document.querySelectorAll('[class*="pgo-style"]');
                return Array.from(els).slice(0, 20).map(e =>
                    `<${e.tagName.toLowerCase()} class="${e.className}" data-correct="${e.getAttribute('data-correct') || ''}">`
                ).join('\\n');
            }""")
            lines.append(f"\n  pgo-style elements (first 20):\n{snippet}")
        except Exception as e:
            lines.append(f"  pgo-style scan error: {e}")

    await scan_frame(page.main_frame, "main")
    for i, frame in enumerate(page.frames[1:], 1):
        await scan_frame(frame, f"iframe-{i}")

    return "\n".join(lines)


async def _test_selectors(page: Page) -> str:
    lines = ["Selector test results:"]
    sel_map = {
        "QUESTION_TEXT": SEL.QUESTION_TEXT,
        "OPTION_CONTAINER": SEL.OPTION_CONTAINER,
        "OPTION_TEXT": SEL.OPTION_TEXT,
        "OPTION_LETTER": SEL.OPTION_LETTER,
        "CORRECT_ANSWER": SEL.CORRECT_ANSWER,
        "NEXT_BUTTON": SEL.NEXT_BUTTON,
    }
    for frames in [page.main_frame, *page.frames[1:]]:
        label = "main" if frames == page.main_frame else frames.url[:60]
        lines.append(f"\n  Frame: {label}")
        for name, sel in sel_map.items():
            try:
                n = await frames.locator(sel).count()
                lines.append(f"    {'OK' if n > 0 else '--'} {name}: {n} match(es)  [{sel[:60]}]")
            except Exception as e:
                lines.append(f"    ERR {name}: {e}")
    return "\n".join(lines)


async def _handle_request(request):
    if any(x in request.resource_type for x in ("xhr", "fetch")):
        _net_log.append({
            "time": datetime.now().isoformat(),
            "method": request.method,
            "url": request.url,
            "post": request.post_data,
        })


async def _handle_response(response):
    if any(x in response.request.resource_type for x in ("xhr", "fetch")):
        try:
            body = await response.text()
        except Exception:
            body = "<binary>"
        entry = next((e for e in reversed(_net_log) if e["url"] == response.url), None)
        if entry:
            entry["status"] = response.status
            entry["response"] = body[:8000]
        else:
            _net_log.append({
                "time": datetime.now().isoformat(),
                "url": response.url,
                "status": response.status,
                "response": body[:8000],
            })
        # Live-print all Pagamo GraphQL traffic
        if "pagamo.org/graphql" in response.url:
            try:
                import json
                post = response.request.post_data or ""
                pdata = json.loads(post) if post else {}
                op = pdata.get("query", "")[:60].replace("\n", " ")
                vars_ = json.dumps(pdata.get("variables", {}), ensure_ascii=False)[:200]
                print(f"\n[graphql] {op}")
                print(f"  vars: {vars_}")
                print(f"  res:  {body[:400]}")
            except Exception:
                pass


async def repl(page: Page):
    print("\n[probe] Browser open. Commands: dom | sel | ws | net | save | quit\n")
    loop = asyncio.get_event_loop()
    while True:
        cmd = await loop.run_in_executor(None, lambda: input("probe> ").strip().lower())
        if cmd == "quit":
            break
        elif cmd == "dom":
            print(await _dump_dom(page))
        elif cmd == "sel":
            print(await _test_selectors(page))
        elif cmd == "ws":
            if not _ws_log:
                print("  (no WebSocket messages captured yet)")
            for m in _ws_log[-20:]:
                print(f"  [{m['dir']}] {m['time']}  {str(m['payload'])[:200]}")
        elif cmd == "net":
            if not _net_log:
                print("  (no network requests captured yet)")
            for r in _net_log[-20:]:
                print(f"  {r.get('method','?')} {r['url'][:100]}  status={r.get('status','?')}")
        elif cmd == "save":
            out = {"ws": _ws_log, "net": _net_log}
            Path("probe_output.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
            print("  Saved to probe_output.json")
        else:
            print("  Unknown command. Use: dom | sel | ws | net | save | quit")


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        page.on("request", _handle_request)
        page.on("response", _handle_response)

        # WebSocket capture
        page.on("websocket", lambda ws: (
            ws.on("framesent",   lambda f: _ws_log.append({"dir": "→", "time": datetime.now().isoformat(), "payload": f.payload})),
            ws.on("framereceived", lambda f: _ws_log.append({"dir": "←", "time": datetime.now().isoformat(), "payload": f.payload})),
            print(f"[probe] WebSocket opened: {ws.url}"),
        ))

        await page.goto("https://www.pagamo.org")
        print("[probe] Browser ready. Log in manually, then explore the site.")
        print(f"[probe] Current URL: {page.url}")

        await repl(page)
        await browser.close()
        print("[probe] Done.")


if __name__ == "__main__":
    asyncio.run(main())
