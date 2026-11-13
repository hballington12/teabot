"""What a destructive action's `plan` returns (D21).

A plan is the diff the action would make, computed without changing anything. The core shows its counts and
first entries to the member, hashes it in canonical form, and applies only if a fresh plan has the same
hash, so a target that changed in between is never acted on blindly.
"""

from pydantic import BaseModel, Field

from teapot.sdk.fields import UntrustedText


class DiffEntry(BaseModel):
    """One change. `change` names its kind, such as `remove` or `skip`; `target` is what it acts on, often a
    member's or a channel's name, so it is untrusted text (D23)."""

    change: str = Field(max_length=32)
    target: UntrustedText
    detail: UntrustedText | None = None


class Diff(BaseModel):
    """Every change the action would make. `counts` is how many entries there are of each kind of change."""

    entries: list[DiffEntry] = Field(default_factory=list[DiffEntry])

    @property
    def counts(self) -> dict[str, int]:
        found: dict[str, int] = {}
        for entry in self.entries:
            found[entry.change] = found.get(entry.change, 0) + 1
        return dict(sorted(found.items()))
