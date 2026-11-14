"""The schema builder (D29): one input model, Discord's command JSON and the MCP tool schema."""

from typing import Any, Literal

import pytest
from pydantic import BaseModel, Field

from teabot.adapters.schema import SchemaError, command_group, mcp_input_schema, slash_fields, tool_name
from teabot.sdk import ActionSpec, ChannelRef, LongText, MemberRef, Risk, RoleRef
from teabot.sdk.inputs import input_fields


class Everything(BaseModel):
    title: str = Field(description="The title", max_length=100)
    count: int
    loud: bool
    channel: ChannelRef = Field(description="Where to post")
    role: RoleRef
    member: MemberRef
    colour: Literal["red", "blue"]
    level: Literal[1, 2, 3]
    body: LongText
    note: str | None = None
    ping: RoleRef | None = None


class Out(BaseModel):
    pass


async def run(_ctx: Any, _data: Any) -> Out:
    return Out()


def spec(model: type[BaseModel], name: str = "announcements.post") -> ActionSpec[Any, Any]:
    return ActionSpec(name, "Post an announcement", model, Out, Risk.WRITE, run)


def test_each_field_type_becomes_its_discord_option() -> None:
    fields = slash_fields(Everything)
    options = {o["name"]: o for o in fields.options}
    assert options["title"] == {
        "type": 3,
        "name": "title",
        "description": "The title",
        "required": True,
        "max_length": 100,
    }
    assert options["count"]["type"] == 4 and options["loud"]["type"] == 5
    assert options["channel"] == {
        "type": 7,
        "name": "channel",
        "description": "Where to post",
        "required": True,
    }
    assert options["role"]["type"] == 8 and options["member"]["type"] == 6
    assert options["colour"]["type"] == 3
    assert options["colour"]["choices"] == [
        {"name": "red", "value": "red"},
        {"name": "blue", "value": "blue"},
    ]
    assert options["level"]["type"] == 4 and [c["value"] for c in options["level"]["choices"]] == [1, 2, 3]
    assert options["note"]["required"] is False and options["ping"] == {
        "type": 8,
        "name": "ping",
        "description": "Ping",
        "required": False,
    }


def test_long_text_goes_to_the_modal_not_the_options() -> None:
    fields = slash_fields(Everything)
    assert "body" not in {o["name"] for o in fields.options}
    assert fields.modal == ("body",)


def test_required_options_come_before_optional_ones() -> None:
    required = [o["required"] for o in slash_fields(Everything).options]
    assert required == sorted(required, reverse=True)


def test_a_missing_description_is_the_field_name_in_words() -> None:
    class Plain(BaseModel):
        channel_id: ChannelRef

    assert slash_fields(Plain).options[0]["description"] == "Channel id"


@pytest.mark.parametrize(
    ("annotation", "why"),
    [
        (float, "float"),
        (list[str], "list"),
        (dict[str, int], "dict"),
        (Literal["a", 1], "Literal"),
        (int | str, "union"),
        (int | str | None, "optional union"),
    ],
)
def test_unsupported_fields_are_refused_by_name(annotation: Any, why: str) -> None:
    model = type("Bad", (BaseModel,), {"__annotations__": {"oops": annotation}})
    with pytest.raises(SchemaError, match="oops"):
        slash_fields(model)


def test_a_nested_model_is_refused() -> None:
    class Inner(BaseModel):
        x: int

    class Outer(BaseModel):
        inner: Inner

    with pytest.raises(SchemaError, match="inner"):
        slash_fields(Outer)


def test_a_plugins_actions_become_one_command_group() -> None:
    class Ping(BaseModel):
        pass

    group = command_group("announcements", [spec(Everything), spec(Ping, "announcements.ping")])
    assert group["name"] == "announcements" and group["type"] == 1
    subcommands = {s["name"]: s for s in group["options"]}
    assert set(subcommands) == {"post", "ping"}
    assert subcommands["post"]["type"] == 1 and subcommands["post"]["description"] == "Post an announcement"
    assert subcommands["ping"]["options"] == []


def test_the_mcp_schema_has_refs_as_digit_strings() -> None:
    schema = mcp_input_schema(spec(Everything))
    assert schema["properties"]["channel"]["type"] == "string"
    assert "body" in schema["properties"] and "channel" in schema["required"]


def test_tool_names_use_underscores() -> None:
    assert tool_name(spec(Everything)) == "announcements_post"


type Size = Literal["s", "m"]


class Aliased(BaseModel):
    size: Size
    maybe: Size | None = None


def test_a_type_alias_is_seen_through() -> None:
    fields = {f.name: f for f in input_fields(Aliased)}
    assert (fields["size"].choices, fields["size"].required) == (("s", "m"), True)
    assert (fields["maybe"].choices, fields["maybe"].required) == (("s", "m"), False)
