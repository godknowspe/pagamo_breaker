# pagamo_breaker

An automation bot for [PaGamO](https://www.pagamo.org/) — the Taiwanese educational quiz game — that uses a real browser for login (bypassing reCAPTCHA) and a pure API client for gameplay.

## How it works

```
Browser (Playwright) ──► Login + Cookie capture
                                │
httpx API client  ◄─────────────┘
        │
        ├─► POST /graphql  answerOnMap        ── start battle, receive questions
        ├─► answer cache  ──► hit? use it      ── free, 100% correct for seen questions
        ├─► LLM (Gemini / Claude)              ── fallback for first-time questions
        ├─► POST /graphql  submitRoom          ── submit answer, get result
        └─► POST /rooms/get_detailed_answer    ── after battle: learn official answers
```

**No DOM scraping** — all game state is delivered via GraphQL JSON. The browser is only opened once to handle reCAPTCHA login; all subsequent battles run headlessly through the API.

**Answer cache:** PaGamO exposes correct answers via `POST /rooms/get_detailed_answer`, but only when you're *not* in an answering room (it's blocked in-room with `should not in room` — you can't peek before submitting). So after each battle ends, the bot fetches the official answers and caches them by `questionId` in `.answer_cache.json`. Question banks repeat, so over time LLM usage drops and accuracy rises to 100% for previously-seen questions.

## Features

- Automatic login with reCAPTCHA handling (Playwright)
- Session cookie caching — browser opens only on first run or after expiry
- Learned answer cache — official answers fetched post-battle, reused for free on repeats
- LLM-powered answering (Google Gemini by default, Claude as fallback) for new questions
- Auto-retry on quota exhaustion with countdown timer
- Auto map scan — finds nearest attackable enemy hex when current target is own territory
- `--repeat N` for multiple battles, `--no-cache` to disable the cache

## Setup

```bash
git clone https://github.com/godknowspe/pagamo_breaker.git
cd pagamo_breaker
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # fill in your credentials
```

## Configuration

Edit `.env`:

```env
PAGAMO_ACCOUNT=your_account@example.com
PAGAMO_PASSWORD=your_password

LLM_PROVIDER=gemini          # gemini | anthropic
GOOGLE_API_KEY=AIza...        # from aistudio.google.com/apikey
GEMINI_MODEL=gemini-2.5-flash

# One of your own territory hexes (used as starting point for auto-scan)
HEX_X=-5121
HEX_Y=-1450

# Your own game character ID
MY_GC_ID=3389027
```

## Usage

```bash
# Attack mode: auto-scans for nearest enemy hex from your starting hex
python main.py

# Run 10 battles in sequence (auto-waits for quota, auto-finds new targets)
python main.py --repeat 10

# Training mode on own hex (no scan needed)
python main.py --hex-x -5121 --hex-y -1450 --type train

# Larger scan radius if default (5) doesn't find enemies
python main.py --radius 10
```

## Finding your hex coordinates and gc_id

1. Open [PaGamO map](https://www.pagamo.org/map) in Chrome
2. Open DevTools → Network tab
3. Click on any of your own hexes
4. Look for the `hexagon_info` request — `x` and `y` are the coordinates
5. Your `MY_GC_ID` appears in any `graphql` response as `gamecharacter.id`

## Project structure

```
main.py                  entry point, CLI argument parsing
pagamo/
  auth.py                Playwright login, cookie caching
  graphql_client.py      GraphQL mutations (answerOnMap, submitRoom, giveUpQuestion)
  map_battle.py          battle loop with quota/room-busy/own-territory recovery
  map_scanner.py         hexagon_info scanner — finds nearest attackable enemy hex
  answer_cache.py        persistent JSON cache keyed by questionId
  question.py            parse GraphQL question objects → clean dict
llm/
  solver.py              Gemini / Claude answer solver
tools/
  probe.py               network + DOM inspector for reverse-engineering new endpoints
```

## Known limits

- **Quota system**: each battle costs ~30 quota; regen rate is 600/hr (~3 min/battle). The bot waits automatically.
- **Fill-in questions**: not yet automated — skipped with a blank answer.
- **Training cap**: own hexes can only be trained up to a server-side limit per period.
- **Scan speed**: auto-scan calls `hexagon_info` per hex; radius=5 checks up to ~120 hexes (~10-30 s).

## Disclaimer

This project is for educational and personal use only. Use responsibly and in accordance with PaGamO's terms of service.
