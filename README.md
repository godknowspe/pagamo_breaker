# pagamo_breaker

An automation bot for [PaGamO](https://www.pagamo.org/) — the Taiwanese educational quiz game — that uses a real browser for login (bypassing reCAPTCHA) and a pure API client for gameplay.

## How it works

```
Browser (Playwright) ──► Login + Cookie capture
                                │
httpx API client  ◄─────────────┘
        │
        ├─► POST /graphql  answerOnMap   ── start battle, receive questions
        ├─► LLM (Gemini / Claude)        ── answer each question
        └─► POST /graphql  submitRoom    ── submit answer, get result
```

**No DOM scraping** — all game state is delivered via GraphQL JSON. The browser is only opened once to handle reCAPTCHA login; all subsequent battles run headlessly through the API.

## Features

- Automatic login with reCAPTCHA handling (Playwright)
- Session cookie caching — browser opens only on first run or after expiry
- LLM-powered answering (Google Gemini by default, Claude as fallback)
- Auto-retry on quota exhaustion with countdown timer
- Auto-recovery from stuck battle rooms (`giveUpQuestion`)
- `--repeat N` flag for running multiple battles in sequence

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

# Default battle target (override with CLI flags)
HEX_X=-5121
HEX_Y=-1450
TARGET_GC_ID=3389027
```

## Usage

```bash
# Single battle at a specific hex coordinate
python main.py --hex-x -5121 --hex-y -1450 --target 3389027

# Run 10 battles in sequence (auto-waits for quota between battles)
python main.py --hex-x -5121 --hex-y -1450 --target 3389027 --repeat 10

# Training mode instead of attack
python main.py --hex-x -5121 --hex-y -1450 --target 3389027 --type train
```

## Finding hex coordinates and target ID

1. Open [PaGamO map](https://www.pagamo.org/map) in Chrome
2. Open DevTools → Network tab
3. Click on an enemy hex to initiate a battle
4. Look for the `hexagon_info` or `answerOnMap` request — the coordinates and `targetGcDecodedId` are in the request body

## Project structure

```
main.py                  entry point, CLI argument parsing
pagamo/
  auth.py                Playwright login, cookie caching
  graphql_client.py      GraphQL mutations (answerOnMap, submitRoom, giveUpQuestion)
  map_battle.py          battle loop with quota/room-busy recovery
  question.py            parse GraphQL question objects → clean dict
  selectors.py           CSS selectors (kept for reference, not actively used)
llm/
  solver.py              Gemini / Claude answer solver
tools/
  probe.py               network + DOM inspector for reverse-engineering new endpoints
```

## Known limits

- **Quota system**: each battle costs ~30 quota; regen rate is 600/hr (~3 min/battle). The bot waits automatically.
- **Fill-in questions**: not yet automated — skipped with a blank answer.
- **Fixed target**: the bot currently attacks a hardcoded hex. Auto-targeting (scan nearby hexes and pick a valid target) is the next planned feature.

## Disclaimer

This project is for educational and personal use only. Use responsibly and in accordance with PaGamO's terms of service.
