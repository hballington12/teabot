"""The plugin SDK's types (WP2.1): illegal values are refused where they enter (D29, D45, D46)."""

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from teapot.sdk import (
    ActionSpec,
    ChannelRef,
    InputError,
    LongText,
    Manifest,
    MemberRef,
    Risk,
    RoleRef,
    Surface,
    UntrustedText,
)


class Post(BaseModel):
    channel: ChannelRef
    role: RoleRef | None = None
    member: MemberRef | None = None
    body: LongText


class Done(BaseModel):
    text: UntrustedText


async def run(_ctx: Any, _data: Post) -> Done:
    return Done(text="ok")


async def plan(_ctx: Any, _data: Post) -> BaseModel:
    return Done(text="diff")


def spec(**overrides: Any) -> ActionSpec[Post, Done]:
    fields: dict[str, Any] = {
        "name": "announcements.post",
        "summary": "Post an announcement",
        "input": Post,
        "output": Done,
        "risk": Risk.WRITE,
        "run": run,
    }
    return ActionSpec(**(fields | overrides))


@pytest.mark.parametrize("given", [123456789012345678, "123456789012345678"])
def test_refs_take_snowflakes_as_ints_or_numeric_strings(given: int | str) -> None:
    assert Post(channel=given, body="x").channel == 123456789012345678  # type: ignore[arg-type]


@pytest.mark.parametrize("given", [0, -5, "12abc", "", 3.5])
def test_refs_refuse_anything_else(given: object) -> None:
    with pytest.raises(ValidationError):
        Post(channel=given, body="x")  # type: ignore[arg-type]


def test_refs_are_strings_in_json_and_its_schema() -> None:
    post = Post(channel=123456789012345678, body="x")
    assert post.model_dump(mode="json")["channel"] == "123456789012345678"
    schema = Post.model_json_schema()["properties"]["channel"]
    assert schema["type"] == "string" and schema["pattern"] == "^[1-9][0-9]{0,19}$"


def test_long_text_is_capped() -> None:
    Post(channel=1, body="x" * 4000)
    with pytest.raises(ValidationError):
        Post(channel=1, body="x" * 4001)


def test_risks_are_ordered() -> None:
    assert Risk.READ < Risk.WRITE < Risk.DESTRUCTIVE


def test_actions_default_to_every_surface() -> None:
    assert spec().surfaces == Surface.ALL == Surface.SLASH | Surface.MCP | Surface.SERVICE


def test_a_destructive_action_needs_a_plan() -> None:
    with pytest.raises(ValueError, match="plan"):
        spec(risk=Risk.DESTRUCTIVE)
    assert spec(risk=Risk.DESTRUCTIVE, plan=plan).plan is plan


@pytest.mark.parametrize(
    "name", ["post", "announcements.", "Announcements.post", "announcements.post.now", "a.post"]
)
def test_action_names_are_plugin_dot_action(name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        spec(name=name)


def test_an_action_knows_its_plugin() -> None:
    assert spec().plugin_id == "announcements"


@pytest.mark.parametrize("plugin_id", ["Bad", "x", "core", "admin", "teapot", "plugin"])
def test_manifests_refuse_bad_and_reserved_ids(plugin_id: str) -> None:
    with pytest.raises(ValueError):
        Manifest(id=plugin_id, version="1.0")


def test_a_manifest_defaults_to_no_config_and_no_migrations() -> None:
    manifest = Manifest(id="announcements", version="1.0")
    assert manifest.migrations is None
    assert manifest.config().model_dump() == {}


@pytest.mark.parametrize("given", [2**64 - 1, str(2**64 - 1)])
def test_the_largest_64_bit_id_is_accepted(given: int | str) -> None:
    assert Post(channel=given, body="x").channel == 2**64 - 1  # type: ignore[arg-type]


@pytest.mark.parametrize("given", [2**64, str(2**64), "99999999999999999999"])
def test_ids_past_64_bits_are_refused(given: int | str) -> None:
    with pytest.raises(ValidationError):
        Post(channel=given, body="x")  # type: ignore[arg-type]


def test_an_action_with_an_unsupported_input_field_cannot_be_built() -> None:
    class Bad(BaseModel):
        ratio: float

    with pytest.raises(InputError, match="ratio"):
        spec(input=Bad)
