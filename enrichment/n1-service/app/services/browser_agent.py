import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import async_playwright, Browser, Page, Playwright

from app.config import settings

logger = logging.getLogger(__name__)

N1_SYSTEM_PROMPT = (
    "You are a browser automation agent. Given a screenshot and an instruction, "
    "predict the next action to take. Respond with JSON only: "
    '{"action": "<click|type|scroll|press|wait|done>", '
    '"params": {<action-specific parameters>}, '
    '"reasoning": "<brief explanation>"}. '
    "For click: params must include x and y (integer pixel coordinates). "
    "For type: params must include text (string to type). "
    "For scroll: params must include direction ('up' or 'down') and amount (pixels, default 500). "
    "For press: params must include key (e.g. 'Escape', 'Enter', 'Tab'). "
    "For wait: params must include duration (seconds, max 5). "
    "For done: params should be empty, meaning the task is complete."
)

MAX_STEPS_PER_TASK = 15


class BrowserAgent:
    """Playwright + Yutori n1 agent loop for deep Instagram profile navigation."""

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._screenshot_dir = Path(settings.screenshot_dir)
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def __aenter__(self) -> "BrowserAgent":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=settings.headless,
        )
        logger.info(
            "Browser launched (headless=%s)", settings.headless
        )
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._browser is not None:
            await self._browser.close()
            logger.info("Browser closed")
        if self._playwright is not None:
            await self._playwright.stop()

    async def navigate_and_capture(
        self,
        url: str,
        max_highlights: int = 3,
        scroll_depth: int = 20,
    ) -> list[bytes]:
        """Navigate an Instagram profile, interact with highlights, scroll posts,
        and return all captured screenshots as a list of PNG bytes."""

        if self._browser is None:
            raise RuntimeError("BrowserAgent must be used as an async context manager")

        context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        screenshots: list[bytes] = []
        action_history: list[str] = []

        try:
            # Step 1: Navigate to the profile
            logger.info("Navigating to %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            # Step 2: Dismiss modals/popups using n1 loop (max 3 steps)
            screenshots_from_dismissal, action_history = await self._dismiss_modals(
                page, action_history
            )
            screenshots.extend(screenshots_from_dismissal)

            # Step 3: Screenshot profile header
            header_screenshot = await self._take_screenshot(page, "profile_header")
            screenshots.append(header_screenshot)

            # Step 4: Navigate highlights
            highlight_screenshots = await self._navigate_highlights(
                page, max_highlights, action_history
            )
            screenshots.extend(highlight_screenshots)

            # Step 5: Scroll through posts
            post_screenshots = await self._scroll_posts(
                page, scroll_depth, action_history
            )
            screenshots.extend(post_screenshots)

        except Exception:
            logger.exception("Error during profile navigation for %s", url)
            # Still return whatever screenshots we managed to capture
        finally:
            await context.close()

        logger.info("Captured %d screenshots for %s", len(screenshots), url)
        return screenshots

    async def _dismiss_modals(
        self, page: Page, action_history: list[str]
    ) -> tuple[list[bytes], list[str]]:
        """Use n1 to detect and dismiss any modals/popups (max 3 steps)."""
        screenshots: list[bytes] = []
        max_dismiss_steps = 3

        for step in range(max_dismiss_steps):
            screenshot_bytes = await self._take_screenshot(
                page, f"dismiss_check_{step}"
            )
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

            instruction = (
                "Look at the current page. If there is a cookie consent banner, "
                "login modal, notification popup, or any overlay blocking the content, "
                "click the button to dismiss/close it (look for 'X', 'Close', "
                "'Not Now', 'Accept', 'Decline' buttons). "
                "If the page content is visible with no overlays, respond with action 'done'."
            )

            result = await self._call_n1(instruction, screenshot_b64, action_history)

            if result.get("action") == "done":
                logger.info("No modals to dismiss at step %d", step)
                break

            action_desc = f"Step {len(action_history) + 1}: {result.get('action')} -- {result.get('reasoning', '')}"
            action_history.append(action_desc)
            logger.info("Dismissing modal: %s", action_desc)

            await self._execute_action(page, result)
            await page.wait_for_timeout(1000)
            screenshots.append(screenshot_bytes)

        return screenshots, action_history

    async def _navigate_highlights(
        self,
        page: Page,
        max_highlights: int,
        action_history: list[str],
    ) -> list[bytes]:
        """Click through Instagram story highlights and capture screenshots."""
        screenshots: list[bytes] = []

        for i in range(max_highlights):
            highlight_num = i + 1
            logger.info("Attempting to open highlight %d/%d", highlight_num, max_highlights)

            # Take screenshot and ask n1 to click the highlight circle
            screenshot_bytes = await self._take_screenshot(
                page, f"before_highlight_{highlight_num}"
            )
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")

            click_instruction = (
                f"Click on highlight circle #{highlight_num} on this Instagram profile. "
                f"The highlight circles are the small circular icons below the bio and "
                f"above the post grid. Click the one at position {highlight_num} from left. "
                f"If there are no more highlight circles, respond with action 'done'."
            )

            result = await self._call_n1(
                click_instruction, screenshot_b64, action_history
            )

            if result.get("action") == "done":
                logger.info("No more highlights found at position %d", highlight_num)
                break

            action_desc = f"Step {len(action_history) + 1}: {result.get('action')} -- clicked highlight {highlight_num}"
            action_history.append(action_desc)

            await self._execute_action(page, result)
            await page.wait_for_timeout(2000)

            # Capture the highlight content
            highlight_screenshot = await self._take_screenshot(
                page, f"highlight_{highlight_num}_content"
            )
            screenshots.append(highlight_screenshot)

            # Ask n1 to close the highlight overlay
            close_screenshot_b64 = base64.b64encode(highlight_screenshot).decode(
                "utf-8"
            )
            close_instruction = (
                "Close this Instagram story/highlight overlay. Look for an 'X' button "
                "in the top-right corner, or click outside the overlay area to close it. "
                "If the overlay is already closed, respond with action 'done'."
            )

            close_result = await self._call_n1(
                close_instruction, close_screenshot_b64, action_history
            )

            if close_result.get("action") != "done":
                close_desc = f"Step {len(action_history) + 1}: {close_result.get('action')} -- closed highlight overlay"
                action_history.append(close_desc)
                await self._execute_action(page, close_result)
                await page.wait_for_timeout(1000)

        return screenshots

    async def _scroll_posts(
        self,
        page: Page,
        scroll_depth: int,
        action_history: list[str],
    ) -> list[bytes]:
        """Scroll through the post grid and capture screenshots in batches."""
        screenshots: list[bytes] = []
        num_batches = max(scroll_depth // 5, 1)

        for batch in range(num_batches):
            logger.info(
                "Scrolling posts batch %d/%d", batch + 1, num_batches
            )

            # Scroll down
            await page.evaluate("window.scrollBy(0, 800)")
            await page.wait_for_timeout(1500)

            # Capture screenshot of the current view
            batch_screenshot = await self._take_screenshot(
                page, f"post_batch_{batch + 1}"
            )
            screenshots.append(batch_screenshot)

            action_desc = f"Step {len(action_history) + 1}: scroll -- scrolled down for post batch {batch + 1}"
            action_history.append(action_desc)

        return screenshots

    async def _call_n1(
        self,
        instruction: str,
        screenshot_b64: str,
        action_history: list[str],
    ) -> dict[str, Any]:
        """Send a screenshot + instruction to the Yutori n1 API and get back
        the next action to execute."""

        # Build action history text
        history_text = "No previous actions."
        if action_history:
            recent = action_history[-5:]  # Last 5 actions
            history_text = "Previous actions:\n" + "\n".join(recent)

        messages = [
            {"role": "system", "content": N1_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{screenshot_b64}"
                        },
                    },
                    {"type": "text", "text": f"Instruction: {instruction}"},
                    {"type": "text", "text": history_text},
                ],
            },
        ]

        payload = {
            "model": settings.n1_model,
            "max_tokens": 500,
            "messages": messages,
        }

        headers = {
            "X-API-Key": settings.yutori_api_key,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{settings.n1_base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)
            logger.debug("n1 response: %s", result)
            return result

        except httpx.HTTPStatusError as exc:
            logger.error(
                "n1 API HTTP error %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return {"action": "done", "params": {}, "reasoning": "API error, stopping"}

        except httpx.RequestError as exc:
            logger.error("n1 API request failed: %s", exc)
            return {"action": "done", "params": {}, "reasoning": "Request error, stopping"}

        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.error("Failed to parse n1 response: %s", exc)
            return {"action": "done", "params": {}, "reasoning": "Parse error, stopping"}

    async def _execute_action(self, page: Page, action: dict[str, Any]) -> None:
        """Execute a browser action returned by n1 on the Playwright page."""
        action_type = action.get("action", "done")
        params = action.get("params", {})

        if action_type == "click":
            x = int(params.get("x", 0))
            y = int(params.get("y", 0))
            logger.debug("Clicking at (%d, %d)", x, y)
            await page.mouse.click(x, y)

        elif action_type == "type":
            text = str(params.get("text", ""))
            logger.debug("Typing: %s", text[:50])
            await page.keyboard.type(text)

        elif action_type == "scroll":
            direction = params.get("direction", "down")
            amount = int(params.get("amount", 500))
            delta = amount if direction == "down" else -amount
            logger.debug("Scrolling %s by %d px", direction, amount)
            await page.mouse.wheel(0, delta)

        elif action_type == "press":
            key = str(params.get("key", "Escape"))
            logger.debug("Pressing key: %s", key)
            await page.keyboard.press(key)

        elif action_type == "wait":
            duration = min(float(params.get("duration", 1)), 5.0)
            logger.debug("Waiting %.1f seconds", duration)
            await page.wait_for_timeout(int(duration * 1000))

        elif action_type == "done":
            logger.debug("n1 signaled done: %s", action.get("reasoning", ""))

        else:
            logger.warning("Unknown action type: %s", action_type)

    async def _take_screenshot(self, page: Page, label: str) -> bytes:
        """Take a full-page screenshot, save to disk, and return the PNG bytes."""
        timestamp = int(time.time() * 1000)
        filename = f"{label}_{timestamp}.png"
        filepath = self._screenshot_dir / filename

        screenshot_bytes = await page.screenshot(type="png")
        filepath.write_bytes(screenshot_bytes)
        logger.debug("Screenshot saved: %s (%d bytes)", filepath, len(screenshot_bytes))

        return screenshot_bytes
