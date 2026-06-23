# CSS selectors for Pagamo DOM elements.
# The hashed suffixes (e.g. DprzUI) are CSS Modules build artifacts and WILL
# change when Pagamo redeploys. Update this file when selectors break.
# Last verified: 2026-04

QUESTION_TEXT = ".question-iframe-container.pgo-style-question-content-wrapper-DprzUI"
OPTION_CONTAINER = ".question-iframe-container.pgo-style-selection-31EiFh"
OPTION_TEXT = ".pgo-style-selection-content-1x0d36"
OPTION_LETTER = ".pgo-style-selection-choice-zKJKfo"
CORRECT_ANSWER = 'div[data-correct="true"]'

# Challenge tower navigation
NEXT_BUTTON = 'button[data-testid="next-button"], button.next-btn, .pgo-next-btn'
