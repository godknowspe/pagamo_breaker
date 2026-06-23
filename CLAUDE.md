# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

`pagamo_breaker` automates playing the [Pagamo](https://www.pagamo.org/) educational quiz platform using browser automation (Playwright) and an LLM (Claude) as a fallback solver.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # fill in credentials
python main.py
```

## Architecture

```
main.py              # entry point, launches Playwright, calls game loop
pagamo/
  auth.py            # REST login (esports.pagamo.org/api/sign_in, RSA-encrypted pw)
  game.py            # main game loop — reads DOM, decides answer, clicks
  selectors.py       # ALL CSS selectors in one place (update here when Pagamo redeploys)
llm/
  solver.py          # Claude API fallback solver (claude-haiku, returns single letter)
```

## Key Design Decisions

**Two-tier answering:**
1. **DOM answer** (`data-correct="true"`): challenge tower exposes correct answers directly in client-side HTML — no LLM needed, 100% accurate.
2. **LLM fallback**: for live games or future modes where answers are not pre-loaded.

**CSS selector fragility:** Pagamo uses CSS Modules, so hashed class names (e.g. `DprzUI`, `31EiFh`) will break on frontend redeploy. All selectors are in `pagamo/selectors.py` — update that single file when things break.

**Auth status:** Login is currently manual (user logs in via browser). The REST endpoint `POST https://esports.pagamo.org/api/sign_in` with RSA-PKCS1v1.5 encrypted password is implemented in `pagamo/auth.py` but not yet wired into the automated flow — the RSA public key in that file may need updating.

## Known Pagamo API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `https://esports.pagamo.org/api/sign_in` | POST | Login (account + RSA-encrypted password) |
| `https://www.pagamo.org/users/personal_information.json` | POST | Get player info / hex count |

## Next Steps

- [ ] Verify/update RSA public key in `pagamo/auth.py` and wire up auto-login
- [ ] Find the correct challenge tower URL path
- [ ] Intercept network traffic to find live game WebSocket endpoint
- [ ] Handle image-based questions (send screenshot to Claude vision)
