from typing import Literal, Union
import click
from dataclasses import dataclass
import subprocess
import os
from multiprocessing.connection import Client, Listener
import time
from playwright import async_api
import asyncio
from .browser_engine import (
    BrowserEngine,
    BrowserCommand,
    NoOpCommand,
    GotoCommand,
    ClickCommand,
    TypeCommand,
    ScrollCommand,
    NavigateCommand,
    ReloadCommand,
)


SERVER_ADDRESS = ("localhost", 6000)


async def browse_start_async() -> None:
    with Listener(SERVER_ADDRESS) as listener:
        async with async_api.async_playwright() as playwright:
            browser = BrowserEngine(playwright)
            await browser.setup()
            while True:
                with listener.accept() as conn:
                    try:
                        command: BrowserCommand = conn.recv()
                        t0 = time.time()
                        print(f"Received command: {command}")
                        await browser.do(command)
                        print(f"Command executed in {time.time() - t0:.2f} seconds")
                        t0 = time.time()
                        print("Generating user-friendly observation")
                        obs = await browser.user_friendly_observation()
                        print(
                            f"User-friendly observation generated in {time.time() - t0:.2f} seconds"
                        )
                    except ValueError as e:
                        obs = await browser.user_friendly_error(e)

                    t0 = time.time()
                    conn.send(obs)
                    print(f"Observation sent in {time.time() - t0:.2f} seconds")


@click.command()
def browse_start() -> None:
    """Runs the server loop"""
    asyncio.run(browse_start_async())


def browse_start_nohup():
    subprocess.Popen(
        ["nohup", "browse-start"],
        stdout=open("/dev/null", "w"),
        stderr=open("/dev/null", "a"),
        preexec_fn=os.setpgrp,
    )
    time.sleep(0.2)


@click.command()
@click.argument("url")
def browse_goto(url: str) -> None:
    """Goes to the url URL"""
    # browse_start_nohup()
    with Client(SERVER_ADDRESS) as conn:
        conn.send(GotoCommand(url))
        click.echo(conn.recv())


@click.command()
@click.argument("id", type=int)
def browse_click(id: int) -> None:
    """Clicks on the element ID"""
    # browse_start_nohup()
    with Client(SERVER_ADDRESS) as conn:
        conn.send(ClickCommand(id))
        click.echo(conn.recv())


@click.command()
@click.argument("id", type=int)
@click.argument("text")
@click.option("--enter", is_flag=True, help="Press enter after typing.")
def browse_type(id: int, text: str, enter: bool) -> None:
    """Types the text TEXT in the element ID. Surround TEXT in quotes."""
    # browse_start_nohup()
    with Client(SERVER_ADDRESS) as conn:
        conn.send(TypeCommand(id, text, enter))
        click.echo(conn.recv())


@click.command()
@click.argument("direction", type=click.Choice(["up", "down"]))
def browse_scroll(direction: Literal["up", "down"]) -> None:
    """Scrolls the page in the DIRECTION direction"""
    # browse_start_nohup()
    with Client(SERVER_ADDRESS) as conn:
        conn.send(ScrollCommand(direction))
        click.echo(conn.recv())


@click.command()
@click.argument("direction", type=click.Choice(["back", "forward"]))
def browse_navigate(direction: Literal["back", "forward"]) -> None:
    """Navigates browser history in the DIRECTION direction"""
    # browse_start_nohup()
    with Client(SERVER_ADDRESS) as conn:
        conn.send(NavigateCommand(direction))
        click.echo(conn.recv())


@click.command()
def browse_reload() -> None:
    """Reloads the page"""
    # browse_start_nohup()
    with Client(SERVER_ADDRESS) as conn:
        conn.send(ReloadCommand())
        click.echo(conn.recv())


@click.command()
def browse_observe() -> None:
    """Observes the page"""
    # browse_start_nohup()
    with Client(SERVER_ADDRESS) as conn:
        conn.send(NoOpCommand())
        click.echo(conn.recv())
