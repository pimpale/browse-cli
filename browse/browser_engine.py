import asyncio
from dataclasses import dataclass
from typing import Literal
from playwright.async_api import (
    async_playwright,
    Playwright,
    ViewportSize,
    BrowserContext,
    Page,
    CDPSession,
)
from .observation_processor import (
    ObsNode,
    get_element_center,
    obs_nodes_to_str,
    process,
)
import math


@dataclass
class NoOpCommand:
    pass


@dataclass
class GotoCommand:
    url: str


@dataclass
class ClickCommand:
    id: int


@dataclass
class TypeCommand:
    id: int
    text: str
    enter: bool


@dataclass
class ScrollCommand:
    direction: Literal["up", "down"]


@dataclass
class NavigateCommand:
    direction: Literal["back", "forward"]


@dataclass
class ReloadCommand:
    pass


BrowserCommand = (
    NoOpCommand
    | GotoCommand
    | ClickCommand
    | TypeCommand
    | ScrollCommand
    | NavigateCommand
    | ReloadCommand
)


class BrowserEngine:
    playwright: Playwright
    context: BrowserContext
    page: Page
    cdpsession: CDPSession
    last_observation: list[ObsNode]

    def __init__(self, playwright: Playwright):
        self.playwright = playwright

    async def setup(self):
        browser = await self.playwright.chromium.launch(
            headless=True,
        )
        self.context = await browser.new_context(viewport={"width": 800, "height": 800})
        self.page = await self.context.new_page()
        self.cdpsession = await self.context.new_cdp_session(self.page)
        self.last_observation = await process(self.page, self.cdpsession)

    async def do(self, command: BrowserCommand):
        match command:
            case NoOpCommand():
                pass
            case GotoCommand(url):
                try:
                    await self.page.goto(url)
                except Exception as e:
                    raise ValueError(f"Failed to navigate to {url}: {e}")
            case ClickCommand(id):
                x, y = await get_element_center(
                    self.last_observation, id, self.cdpsession
                )
                await self.page.mouse.move(x, y, steps=20)
                await self.page.mouse.click(x, y)
            case TypeCommand(id, text, enter):
                if enter:
                    text += "\n"
                x, y = await get_element_center(
                    self.last_observation, id, self.cdpsession
                )
                await self.page.mouse.move(x, y, steps=20)
                await self.page.mouse.click(x, y)
                focused = await self.page.locator("*:focus").all()
                if focused == []:
                    raise ValueError("Element was not focusable")
                text_input = focused[0]
                # clear
                await text_input.clear()
                await text_input.type(text, delay=100)
            case ScrollCommand(direction):
                assert self.page.viewport_size is not None
                magnitude = self.page.viewport_size["height"]
                amount = -magnitude if direction == "up" else magnitude
                await self.page.evaluate(f"window.scrollBy(0, {amount});")
            case NavigateCommand(direction):
                match direction:
                    case "back":
                        await self.page.go_back()
                    case "forward":
                        await self.page.go_forward()
            case ReloadCommand():
                await self.page.reload()

    async def scroll_percentage(self) -> float:
        return await self.page.evaluate(
            "(document.documentElement.scrollTop + document.body.scrollTop) / (document.documentElement.scrollHeight - document.documentElement.clientHeight) * 100"
        )

    async def user_friendly_observation(self) -> str:
        self.last_observation = await process(self.page, self.cdpsession)

        content = obs_nodes_to_str(self.last_observation)

        url_text = f"Viewing URL: {self.page.url }"

        scroll_percentage = await self.scroll_percentage()

        scroll_text = (
            "You are viewing the entire page."
            if math.isnan(scroll_percentage)
            else f"You are only viewing part of the page. Scroll percentage: {scroll_percentage:.2f}%"
        )

        return f"{url_text}\n\n{scroll_text}\n\nPage Content:\n\n{content}"

    async def user_friendly_error(self, e: ValueError) -> str:
        observation = await self.user_friendly_observation()
        return f"Error: {e.args[0]}\n\n{observation}"
