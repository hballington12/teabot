"""ctx.http reaches the hosts a plugin declares, and refuses any other."""

import pytest

from teabot.core.registry import ActionFailed
from teabot.sdk import Context, EmptyConfig, Plugin, ReceivedMessage
from teabot.testing import FakeChannel, HarnessFactory, PluginHarness

plugin = Plugin("wom", hosts=["api.wiseoldman.net"])
type Ctx = Context[EmptyConfig]


@plugin.action()
async def rank(ctx: Ctx, name: str) -> str:
    """A player's account type.

    Args:
        name: Their name.
    """
    found = await ctx.http.get(f"https://api.wiseoldman.net/v2/players/{name}")
    return str(found.json()["type"]) if found.ok else f"not found ({found.status})"


@plugin.action()
async def elsewhere(ctx: Ctx, url: str) -> str:
    """Fetch a URL.

    Args:
        url: Which.
    """
    return (await ctx.http.get(url)).text


heard: list[str] = []


@plugin.on_message
async def lookup(ctx: Ctx, message: ReceivedMessage) -> None:
    found = await ctx.http.get(f"https://api.wiseoldman.net/v2/players/{message.content}")
    heard.append(str(found.json()["type"]))


@pytest.fixture
async def harness(teabot_harness: HarnessFactory) -> PluginHarness:
    return await teabot_harness(plugin)


async def test_a_declared_host_is_reached_and_its_reply_read(harness: PluginHarness) -> None:
    harness.web.reply("https://api.wiseoldman.net/v2/players/zezima", json_body={"type": "regular"})
    harness.web.reply("https://api.wiseoldman.net/v2/players/nobody", status=404)
    assert await harness.call(rank, name="zezima") == "regular"
    assert await harness.call(rank, name="nobody") == "not found (404)"
    assert harness.web.requests[0].headers["user-agent"] == "teabot plugin wom"


@pytest.mark.parametrize(
    "url", ["https://example.com/", "https://evil.api.wiseoldman.net.example/", "file:///etc/passwd"]
)
async def test_any_other_host_is_refused(harness: PluginHarness, url: str) -> None:
    with pytest.raises(ActionFailed, match=r"HostNotDeclared.*may not reach"):
        await harness.call(elsewhere, url=url)
    assert harness.web.requests == []


async def test_an_event_handler_reaches_the_plugins_hosts(harness: PluginHarness) -> None:
    heard.clear()
    harness.web.reply("https://api.wiseoldman.net/v2/players/zezima", json_body={"type": "regular"})
    channel = harness.guild.add_channel(FakeChannel(name="chat"))
    await harness.post(channel, harness.member, "zezima")
    assert heard == ["regular"]
