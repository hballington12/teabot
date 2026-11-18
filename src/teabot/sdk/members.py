"""The member directory, as plugins read it (D55): `ctx.members`, for a plugin that declares
`Plugin(..., reads=["members"])`.

A filter can also match labels another plugin keeps about members (`labels_from`), which count only while that
plugin's labels are fresh. `MemberFilter` is the filter `admin.members` takes too, so an assistant can preview a
filter with `admin.members` and pass the same fields to a plugin's action, and the counts match. Names are
member-written, so they are untrusted text (D23).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from teabot.sdk.actions import ActionError
from teabot.sdk.fields import MemberRef, RoleRef
from teabot.sdk.labels import MAX_LENGTH

type JoinMethod = Literal[
    "unknown", "bot", "integration", "discovery", "hub", "invite", "vanity_url", "manual_verification"
]
"""How a member joined, as Discord's member search reports it."""

READS = frozenset({"members"})
"""What `Plugin(..., reads=[...])` may name."""
DAY = r"^\d{4}-\d{2}-\d{2}$"
FIND_LIMIT = 1000


class MemberFilter(BaseModel):
    """Which present members, by their roles, when they joined, how, and more. Days are UTC days, as YYYY-MM-DD,
    inclusive. Every field left out matches everyone."""

    roles_any: list[RoleRef] = Field(default=[], max_length=10, description="Has at least one of these roles")
    roles_all: list[RoleRef] = Field(default=[], max_length=10, description="Has every one of these roles")
    roles_none: list[RoleRef] = Field(default=[], max_length=10, description="Has none of these roles")
    no_roles: bool = Field(default=False, description="Has no roles at all")
    joined_after: str | None = Field(default=None, pattern=DAY, description="Joined on or after this day")
    joined_before: str | None = Field(default=None, pattern=DAY, description="Joined on or before this day")
    created_after: str | None = Field(
        default=None, pattern=DAY, description="Account made on or after this day"
    )
    created_before: str | None = Field(
        default=None, pattern=DAY, description="Account made on or before this day"
    )
    join_method: list[JoinMethod] = Field(default=[], max_length=8, description="Joined by any of these ways")
    invite_code: str | None = Field(default=None, max_length=32, description="Joined with this invite")
    inviter: MemberRef | None = Field(default=None, description="Joined with an invite this member made")
    boosting: bool | None = Field(default=None, description="Boosts the server, or does not")
    timed_out: bool | None = Field(default=None, description="Is timed out now, or is not")
    pending: bool | None = Field(default=None, description="Has not yet passed membership screening, or has")
    bots: bool | None = Field(default=None, description="Only bots, or only people; both when left out")
    labels_from: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Has a label from this plugin; with labels_any or labels_all, those labels",
    )
    labels_any: list[str] = Field(
        default=[], max_length=10, description="Has at least one of these labels from labels_from"
    )
    labels_all: list[str] = Field(
        default=[], max_length=10, description="Has every one of these labels from labels_from"
    )

    @model_validator(mode="after")
    def _labels_need_a_plugin(self) -> "MemberFilter":
        if (self.labels_any or self.labels_all) and self.labels_from is None:
            raise ValueError("labels_any and labels_all need labels_from, the plugin whose labels they are")
        if any(len(label) > MAX_LENGTH for label in [*self.labels_any, *self.labels_all]):
            raise ValueError(f"a label is at most {MAX_LENGTH} characters")
        return self


class PeopleFilter(MemberFilter):
    """A `MemberFilter` that matches people only unless it says otherwise, for changes made to members."""

    bots: bool | None = Field(
        default=False, description="Only bots, or only people (the default); null for both"
    )


@dataclass(frozen=True)
class DirectoryMember:
    """A present member, as the directory knows them.

    - `user_id`, `name` (their username), `display_name` (their nickname, else their display name, else their
      username) and `nickname`, which are member-written text (D23).
    - `role_ids`, `joined_at`, which Discord may leave unknown, and `bot`.
    - `join_method`, such as `invite`, or `unknown`.
    """

    user_id: int
    name: str
    display_name: str
    nickname: str | None
    role_ids: tuple[int, ...]
    joined_at: datetime | None
    bot: bool
    join_method: str


class DirectoryUnavailable(ActionError):
    """The server's directory is not ready: its first copy is still being made, or it is off above the instance's
    member limit. The message says which."""


class NotAuthorized(ActionError):
    """A job's grant no longer holds: the member who confirmed the work, or their token, may no longer do it. The
    message says why."""


class NotDeclared(RuntimeError):
    """The plugin reads what it did not declare in `Plugin(..., reads=[...])`."""


class Members(Protocol):
    """The server's member directory (D55), for a plugin that declares `reads=["members"]`."""

    async def count(self, *filters: MemberFilter) -> int:
        """How many present members match every one of `filters`."""
        ...

    async def find(
        self, *filters: MemberFilter, after: int = 0, limit: int = FIND_LIMIT
    ) -> list[DirectoryMember]:
        """Present members who match every one of `filters`, in user ID order, with IDs above `after`, at most
        `limit`, up to 1,000. Page by passing the last one's `user_id` as `after`."""
        ...
