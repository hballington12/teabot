"""How the core's parts fit together, shared by `teabot run` and `teabot.testing`, so tests run the real wiring.

The registry serves the loaded plugins and the admin plugin's built-in groups (`/plugins`, `/audit`,
`/tokens`, `/admin`). Enabling or disabling a plugin queues a command sync, `/tokens create` checks
allow-lists against every action the registry knows, and destructive actions plan then apply (D21). The
core's own job handlers are registered here (command syncs, audit posts, plan applies, outbox posts, plugin event
deliveries), and every loaded plugin's.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from teabot.auth.tokens import Tokens
from teabot.builtin.admin import Admin
from teabot.builtin.events_feed import EventsFeed
from teabot.builtin.lookups import Lookups
from teabot.builtin.members import Members
from teabot.builtin.permissions import Permissions
from teabot.builtin.tokens import TokenCommands
from teabot.core.audit import POST_HANDLER, AuditLog, ChannelSource, Kinds, PostAudit
from teabot.core.command_sync import SYNC_HANDLER, CommandApi, CommandSync
from teabot.core.directory.labels import LabelService
from teabot.core.events import Events
from teabot.core.grants import Grants
from teabot.core.loader import LoadReport
from teabot.core.outbox import POST_MESSAGE, Outbox
from teabot.core.plans import Plans
from teabot.core.plugin_events import DELIVER_HANDLER, Deliver
from teabot.core.plugin_jobs import JobServices, register_plugin_jobs
from teabot.core.queue import APPLY_HANDLER, JobContext, Queue
from teabot.core.recurring import Recurring
from teabot.core.registry import ActionSource, Call, GuildSource, Registry, sources_from
from teabot.core.voice import DiscordConnector, VoiceService
from teabot.db.pool import Pools, Queries
from teabot.sdk.inputs import input_fields
from teabot.sdk.plans import Diff

APPLY_TIMEOUT = timedelta(hours=1)


class Client(GuildSource, ChannelSource, CommandApi, Protocol):
    """What the core needs from the Discord client."""


@dataclass(frozen=True)
class Core:
    registry: Registry
    sources: dict[str, ActionSource]
    statuses: dict[str, str]
    sync: CommandSync
    tokens: Tokens
    queue: Queue
    events: Events
    outbox: Outbox
    recurring: Recurring
    voice: VoiceService
    members: Members


def assemble(
    report: LoadReport, pools: Pools, queue: Queue, client: Client, public_url: str | None = None
) -> Core:
    """The core's parts, wired together. `public_url` is the instance's public address, if it has one. Voice
    connects through discord.py; a test swaps `core.voice.connector` for a fake (D54)."""
    statuses = report.labels()
    configs = {p: loaded.plugin.manifest.config for p, loaded in report.loaded.items()}
    admin = Admin(pools.core_db(), statuses=statuses, configs=configs)
    tokens = Tokens(pools.core_db())
    if public_url:
        token_commands = TokenCommands(tokens, f"{public_url.rstrip('/')}/mcp", local=False)
    else:
        token_commands = TokenCommands(tokens)
    lookups = Lookups(pools.core_db())
    members = Members(pools.core_db())
    fresh_for = {
        plugin_id: loaded.plugin.manifest.labels_fresh_for
        for plugin_id, loaded in report.loaded.items()
        if "labels" in loaded.plugin.manifest.writes
    }
    labels = LabelService(pools.core_db(), fresh_for)
    members.labels = labels
    admin_tools = lookups.sources(members.specs(), Permissions().specs(), EventsFeed(pools.core_db()).specs())
    sources = sources_from(report.loaded) | admin.sources() | token_commands.sources() | admin_tools
    sync = CommandSync(pools.core_db(), queue, sources, client)
    admin.on_change = sync.request
    audit = AuditLog(queue)
    plans = Plans(queue, audit)
    listeners = {plugin_id: loaded.events for plugin_id, loaded in report.loaded.items() if loaded.events}
    voice = VoiceService(pools.core_db(), queue, DiscordConnector(client), listeners)
    registry = Registry(sources, pools=pools, client=client, audit=audit, plans=plans)
    registry.voice = voice
    registry.labels = labels
    token_commands.known = frozenset(registry.actions)

    async def apply(ctx: JobContext) -> None:
        audit_id = int(ctx.job.payload["audit_id"])
        request = await plans.apply_request(audit_id)
        call = Call(request.action, request.guild_id, request.actor, request.raw_input)
        diff = Diff.model_validate(ctx.job.payload.get("diff", {}))
        await registry.run_apply(call, audit_id, ctx.report, diff)

    queue.register("core", SYNC_HANDLER, sync)
    kinds: Kinds = {
        name: {f.name: f.kind for f in input_fields(spec.input)} for name, spec in registry.actions.items()
    }
    queue.register("core", POST_HANDLER, PostAudit(pools.core_db(), client, kinds))
    # An apply waits out Discord's rate limits, so a change to hundreds of members can rightly take a while.
    queue.register("core", APPLY_HANDLER, apply, APPLY_TIMEOUT)
    outbox = Outbox(pools.core_db(), client)
    queue.register("core", POST_MESSAGE, outbox)
    subscribers = {p: loaded.subscriptions for p, loaded in report.loaded.items() if loaded.subscriptions}
    queue.register("core", DELIVER_HANDLER, Deliver(pools.core_db(), queue, subscribers))
    recurring = Recurring(pools.core_db(), {p: loaded.recurring for p, loaded in report.loaded.items()})
    grants = Grants(registry, tokens, audit)
    register_plugin_jobs(queue, report.loaded, pools, client, JobServices(recurring, voice, grants, labels))
    late = {plugin_id: loaded.late for plugin_id, loaded in report.loaded.items() if loaded.late}
    events = Events(pools.core_db(), queue, listeners, late)

    async def labels_changed(guild_id: int, plugin_id: str, within: Queries) -> None:
        await events.fire(guild_id, "labels_changed", {"plugin": plugin_id}, within=within)

    labels.notify = labels_changed

    async def enabled(guild_id: int, plugin_id: str, user_id: int) -> None:
        await recurring.ensure(guild_id, plugin_id)
        await events.enabled(guild_id, plugin_id, user_id)
        if plugin_id in fresh_for:
            # Its labels count again from now, so whatever reads them looks again.
            await events.fire(guild_id, "labels_changed", {"plugin": plugin_id})

    admin.on_enabled = enabled
    return Core(registry, sources, statuses, sync, tokens, queue, events, outbox, recurring, voice, members)
