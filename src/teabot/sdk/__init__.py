"""The public plugin API (D45). Plugins import from here and nothing else in teabot.

It follows semantic versioning from 1.0, as the `teabot` package's version. Additions are minor releases (D6).
A breaking change needs a major release, and the old form keeps working with a deprecation warning for at
least one minor release first. Only the names below are public: the submodules of `teabot.sdk` and everything
else in `teabot` are internal and may change in any release.

A plugin:
- `Plugin`: the object a package's `teabot.plugins` entry point names, with a `Manifest` and a `setup`.
- `Manifest`: the plugin's id, version, config model and migrations. `EmptyConfig` is the config of none.
- `Registrar`: what `setup` registers actions and jobs with.
- `InvalidPluginId`: what `Manifest` raises for an id that breaks D46.

Actions:
- `ActionSpec`: one action, with its input and output models, `Risk`, permissions and `Surface`.
- `ActionContext`: what one call receives: the server, the `Actor`, the plugin's `Db`, its config and queue.
- `Actor`: the member who made the call, and `Via`, the front door it came through.
- `ActionError`: raised to tell the member what went wrong.
- `InputError`: what `ActionSpec` raises for an input field type D29 does not allow.

Field types (D23, D29):
- `ChannelRef`, `RoleRef`, `MemberRef`: Discord IDs, which are strings in JSON.
- `LongText`: multi-line text, which Discord collects in a modal.
- `UntrustedText`: member-written text in an output, which MCP marks as untrusted.

Plans (D21):
- `Diff` and `DiffEntry`: what a destructive action's `plan` returns.

The database (D9, D30):
- `Db`: the plugin's own tables. `Queries` runs SQL and returns `Row`s; `Tx` is a transaction.
- `Scheduler`: queues jobs (D31). `JobContext` is what a job receives, and `JobHandler` runs it.
"""

from teabot.sdk.actions import ActionContext, ActionError, ActionSpec, Actor, Risk, Surface, Via
from teabot.sdk.db import Db, Queries, Row, Scheduler, Tx
from teabot.sdk.fields import ChannelRef, LongText, MemberRef, RoleRef, UntrustedText
from teabot.sdk.ids import InvalidPluginId
from teabot.sdk.inputs import InputError
from teabot.sdk.plans import Diff, DiffEntry
from teabot.sdk.plugin import EmptyConfig, JobContext, JobHandler, Manifest, Plugin, Registrar

__all__ = [
    "ActionContext",
    "ActionError",
    "ActionSpec",
    "Actor",
    "ChannelRef",
    "Db",
    "Diff",
    "DiffEntry",
    "EmptyConfig",
    "InputError",
    "InvalidPluginId",
    "JobContext",
    "JobHandler",
    "LongText",
    "Manifest",
    "MemberRef",
    "Plugin",
    "Queries",
    "Registrar",
    "Risk",
    "RoleRef",
    "Row",
    "Scheduler",
    "Surface",
    "Tx",
    "UntrustedText",
    "Via",
]
