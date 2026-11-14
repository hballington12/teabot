"""Field types for action inputs and outputs (D23, D29).

- `ChannelRef`, `RoleRef` and `MemberRef` hold a Discord ID. They accept a positive integer or a string of
  digits, and are strings in JSON and its schema, because snowflakes exceed JavaScript's safe integers.
- `LongText` is multi-line text up to Discord's modal limit, which slash options cannot hold.
- `UntrustedText` marks member-written text in outputs, which MCP wraps in an untrusted marker.
"""

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler, StringConstraints
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

SNOWFLAKE_PATTERN = "^[1-9][0-9]{0,19}$"
_SNOWFLAKE_RE = re.compile(SNOWFLAKE_PATTERN)
_MAX_SNOWFLAKE = 2**64 - 1
LONG_TEXT_MAX = 4000


def parse_snowflake(value: object) -> int:
    """A Discord ID from an int or a string of digits. Anything else is refused."""
    if isinstance(value, int) and not isinstance(value, bool):
        number = value
    elif isinstance(value, str) and _SNOWFLAKE_RE.fullmatch(value):
        number = int(value)
    else:
        raise ValueError("a Discord ID is a positive integer or a string of digits")
    if not 0 < number <= _MAX_SNOWFLAKE:
        raise ValueError("a Discord ID is a positive 64-bit integer")
    return number


@dataclass(frozen=True)
class Ref:
    """A Discord ID of one kind: parsed once where it enters, a string in JSON (D29)."""

    kind: Literal["channel", "role", "member"]

    def __get_pydantic_core_schema__(
        self, _source: Any, _handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            parse_snowflake,
            serialization=core_schema.plain_serializer_function_ser_schema(str, when_used="json"),
        )

    def __get_pydantic_json_schema__(
        self, _schema: core_schema.CoreSchema, _handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        return {"type": "string", "pattern": SNOWFLAKE_PATTERN}


@dataclass(frozen=True)
class Long:
    """Marks multi-line text, which the slash adapter collects in a modal."""


@dataclass(frozen=True)
class Untrusted:
    """Marks text written by members, which the MCP adapter wraps (D23)."""


ChannelRef = Annotated[int, Ref("channel")]
RoleRef = Annotated[int, Ref("role")]
MemberRef = Annotated[int, Ref("member")]
LongText = Annotated[str, Long(), StringConstraints(max_length=LONG_TEXT_MAX)]
UntrustedText = Annotated[str, Untrusted()]
