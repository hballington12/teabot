"""What a destructive action's `plan` returns (D21).

A plan is the diff the action would make, computed without changing anything. The core shows its counts and
first entries to the member, hashes it in canonical form, and applies only if a fresh plan has the same
hash, so a target that changed in between is never acted on blindly.
"""

from pydantic import BaseModel, Field

from teabot.sdk.fields import UntrustedText


class DiffEntry(BaseModel):
    """One change. `change` names its kind, such as `remove` or `skip`; `target` is what it acts on, often a
    member's or a channel's name, so it is untrusted text (D23). `key` identifies it for the apply, such as a row's
    id: it is part of the plan's hash but never shown, so the apply can act on the diff without parsing text."""

    change: str = Field(max_length=32)
    target: UntrustedText
    detail: UntrustedText | None = None
    key: int | str | None = None


class Diff(BaseModel):
    """Every change the action would make, as `entries`. `notes` are lines shown above them, such as counts or an
    estimate, which are never hashed, so only the entries decide whether a plan is stale."""

    entries: list[DiffEntry] = Field(default_factory=list[DiffEntry])
    notes: list[UntrustedText] = Field(default_factory=list[UntrustedText])

    @property
    def counts(self) -> dict[str, int]:
        """How many entries there are of each kind of change, by kind."""
        found: dict[str, int] = {}
        for entry in self.entries:
            found[entry.change] = found.get(entry.change, 0) + 1
        return dict(sorted(found.items()))


class HandedOff(BaseModel):
    """What a destructive action's apply returns when it hands its work to a job of the plugin's, such as a change
    to thousands of members: what follows it, by `id`, and a line for the member. The apply's audit row then ends
    "handed off", and the job records the outcome with `ctx.record_outcome`."""

    id: str
    text: str
