"""The public plugin API (D45). Plugins import from here and nothing else in teabot.

It follows semantic versioning from 1.0, as the `teabot` package's version. Additions are minor releases (D6).
A breaking change needs a major release, and the old form keeps working with a deprecation warning for at
least one minor release first. Only the names below are public: the submodules of `teabot.sdk` and everything
else in `teabot` are internal and may change in any release.

A plugin:
- `Plugin`: a plugin, with its id and its config model. `@plugin.action` makes a function an `Action`, and
  `@plugin.job` makes one a `Job`.
- `Context`: what an action or a job receives: the server, the actor, the config, the database and the time.
- `READ`, `WRITE` and `DESTRUCTIVE`: an action's `Risk`. `Permission` names what a member needs.
- `Manifest`: a plugin's id, version, config model and migrations. `EmptyConfig` is the config of none.
- `LoadablePlugin`: what an entry point may name: a `Plugin`, or any object with a `Manifest` and a `setup`
  that registers with a `Registrar`.
- `InvalidPluginId`: what a plugin with an id that breaks D46 raises.

Actions:
- `ActionSpec`: one action, with its input and output models, `Risk`, permissions and `Surface`.
- `ActionContext`: what one call receives: the server, the `Actor`, the plugin's `Db`, its config and queue.
- `Actor`: the member who made the call, and `Via`, the front door it came through. `SYSTEM` is the actor of a
  job nobody started.
- `ActionError`: raised to tell the member what went wrong.
- `InputError`: what `ActionSpec` raises for an input field type D29 does not allow.

The server (D45):
- `Guild`: the server, to find a `TextChannel`, any `Channel`, a `Role` or a `Member`, and to ban. A channel's `send`
  returns a `Message`, and mentions nobody unless asked. Members can be given roles, renamed, timed out, kicked and
  sent a direct message, as the bot. `File` attaches a file; `Ban` is one of the server's bans. `ChannelKind` is what
  sort of channel a `Channel` is.

Field types (D23, D29):
- `ChannelRef`, `RoleRef`, `MemberRef`: Discord IDs, which are strings in JSON.
- `LongText`: multi-line text, which Discord collects in a modal.
- `UntrustedText`: member-written text in an output, which MCP marks as untrusted.

Plans (D21):
- `Diff` and `DiffEntry`: what a destructive action's `plan` returns.

The database (D9, D30):
- `Db`: the plugin's own tables. `Queries` runs SQL and returns `Row`s; `Tx` is a transaction.
- `Scheduler`: queues jobs (D31), a `Bound` job or one named by its handler. `JobContext` is what a job
  receives, and `JobHandler` runs it.
"""

from teabot.sdk.actions import SYSTEM, ActionContext, ActionError, ActionSpec, Actor, Risk, Surface, Via
from teabot.sdk.authoring import DESTRUCTIVE, READ, WRITE, Action, Context, Job, Plugin
from teabot.sdk.db import Bound, Db, Queries, Row, Scheduler, Tx
from teabot.sdk.fields import ChannelRef, LongText, MemberRef, RoleRef, UntrustedText
from teabot.sdk.guild import Ban, Channel, ChannelKind, File, Guild, Member, Message, Role, TextChannel
from teabot.sdk.ids import InvalidPluginId
from teabot.sdk.inputs import InputError
from teabot.sdk.permissions import Permission
from teabot.sdk.plans import Diff, DiffEntry
from teabot.sdk.plugin import EmptyConfig, JobContext, JobHandler, LoadablePlugin, Manifest, Registrar

__all__ = [
    "DESTRUCTIVE",
    "READ",
    "SYSTEM",
    "WRITE",
    "Action",
    "ActionContext",
    "ActionError",
    "ActionSpec",
    "Actor",
    "Ban",
    "Bound",
    "Channel",
    "ChannelKind",
    "ChannelRef",
    "Context",
    "Db",
    "Diff",
    "DiffEntry",
    "EmptyConfig",
    "File",
    "Guild",
    "InputError",
    "InvalidPluginId",
    "Job",
    "JobContext",
    "JobHandler",
    "LoadablePlugin",
    "LongText",
    "Manifest",
    "Member",
    "MemberRef",
    "Message",
    "Permission",
    "Plugin",
    "Queries",
    "Registrar",
    "Risk",
    "Role",
    "RoleRef",
    "Row",
    "Scheduler",
    "Surface",
    "TextChannel",
    "Tx",
    "UntrustedText",
    "Via",
]
