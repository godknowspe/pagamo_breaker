"""
Core game loop for Pagamo challenge tower automation.

Flow:
  1. Read question text from DOM
  2. Check if data-correct="true" is present (challenge tower mode)
     → If yes: click it directly (no LLM needed)
     → If no:  send question + options to LLM, click returned letter
  3. Click next, repeat
"""
import asyncio
import os
from playwright.async_api import Page

from pagamo import selectors
from llm import solver


async def _read_question(page: Page) -> str:
    el = page.locator(selectors.QUESTION_TEXT).first
    await el.wait_for(timeout=10000)
    return (await el.inner_text()).strip()


async def _read_options(page: Page) -> dict[str, str]:
    containers = page.locator(selectors.OPTION_CONTAINER)
    count = await containers.count()
    options = {}
    for i in range(count):
        c = containers.nth(i)
        letter_el = c.locator(selectors.OPTION_LETTER)
        text_el = c.locator(selectors.OPTION_TEXT)
        letter = (await letter_el.inner_text()).strip()
        text = (await text_el.inner_text()).strip()
        if letter:
            options[letter] = text
    return options


async def _get_correct_from_dom(page: Page) -> str | None:
    """Returns the letter of the DOM-marked correct answer, or None."""
    correct_els = page.locator(selectors.CORRECT_ANSWER)
    count = await correct_els.count()
    if count == 0:
        return None
    # Find which option container has data-correct="true"
    containers = page.locator(selectors.OPTION_CONTAINER)
    n = await containers.count()
    for i in range(n):
        c = containers.nth(i)
        data_correct = await c.get_attribute("data-correct")
        if data_correct == "true":
            letter_el = c.locator(selectors.OPTION_LETTER)
            return (await letter_el.inner_text()).strip()
    # Fallback: click the first marked element
    await correct_els.first.click()
    return None


async def _click_option(page: Page, letter: str) -> None:
    containers = page.locator(selectors.OPTION_CONTAINER)
    n = await containers.count()
    for i in range(n):
        c = containers.nth(i)
        letter_el = c.locator(selectors.OPTION_LETTER)
        if (await letter_el.inner_text()).strip() == letter:
            await c.click()
            return
    raise ValueError(f"Option {letter!r} not found in DOM")


async def run_challenge_tower(page: Page) -> None:
    """
    Runs the challenge tower loop until the page no longer shows questions.
    LLM provider and API key are read from env (LLM_PROVIDER, GOOGLE_API_KEY, etc.)
    """
    question_num = 0
    while True:
        try:
            await page.wait_for_selector(selectors.QUESTION_TEXT, timeout=8000)
        except Exception:
            print("[game] No more questions found. Done.")
            break

        question_num += 1
        question = await _read_question(page)
        options = await _read_options(page)
        print(f"\n[Q{question_num}] {question}")
        for k, v in options.items():
            print(f"  {k}. {v}")

        # Try DOM-based answer first (challenge tower exposes data-correct)
        letter = await _get_correct_from_dom(page)

        if letter:
            print(f"  → DOM answer: {letter}")
        else:
            # Fallback to LLM
            letter = solver.solve(question, options)
            print(f"  → LLM answer: {letter}")

        await _click_option(page, letter)
        await asyncio.sleep(0.5)

        # Click next if available
        try:
            next_btn = page.locator(selectors.NEXT_BUTTON).first
            await next_btn.wait_for(timeout=3000)
            await next_btn.click()
            await asyncio.sleep(0.8)
        except Exception:
            # No next button — might be auto-advancing
            await asyncio.sleep(1.5)
