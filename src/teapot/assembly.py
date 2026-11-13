"""How the core's parts fit together, shared by `teapot run` and `teapot.testing`, so tests run the real wiring.

The registry serves the loaded plugins and the admin plugin's built-in groups (`/plugins`, `/audit`,
`/tokens`, `/admin`). Enabling or disabling a plugin queues a command sync, `/tokens create` checks
allow-lists against every action the registry knows, and destructive actions plan then apply (D21). The
core's own job handlers are registered here: command syncs, audit posts and plan applies.
"""

from dataclasses import dataclass
from typing import Protocol

from teapot.auth.tokens import Tokens
from teapot.builtin.admin import Admin
from teapot.builtin.lookups import Lookups
from teapot.builtin.tokens import TokenCommands
from teapot.core.audit import POST_HANDLER, AuditLog, ChannelSource, PostAudit
from teapot.core.command_sync import SYNC_HANDLER, CommandApi, CommandSync
from teapot.core.loader import LoadReport
from teapot.core.plans import Plans
from teapot.core.queue import APPLY_HANDLER, JobContext, Queue
from teapot.core.registry import ActionSource, Call, GuildSource, Registry, sources_from
from teapot.db.pool import Pools


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


def assemble(report: LoadReport, pools: Pools, queue: Queue, client: Client) -> Core:
    statuses = report.labels()
    configs = {p: loaded.plugin.manifest.config for p, loaded in report.loaded.items()}
    admin = Admin(pools.core_db(), statuses=statuses, configs=configs)
    tokens = Tokens(pools.core_db())
    token_commands = TokenCommands(tokens)
    lookups = Lookups(pools.core_db())
    sources = sources_from(report.loaded) | admin.sources() | token_commands.sources() | lookups.sources()
    sync = CommandSync(pools.core_db(), queue, sources, client)
    admin.on_change = sync.request
    audit = AuditLog(queue)
    plans = Plans(queue, audit)
    registry = Registry(sources, pools=pools, client=client, audit=audit, plans=plans)
    token_commands.known = frozenset(registry.actions)

    async def apply(ctx: JobContext) -> None:
        audit_id = int(ctx.job.payload["audit_id"])
        request = await plans.apply_request(audit_id)
        call = Call(request.action, request.guild_id, request.actor, request.raw_input)
        await registry.run_apply(call, audit_id, ctx.report)

    queue.register("core", SYNC_HANDLER, sync)
    queue.register("core", POST_HANDLER, PostAudit(pools.core_db(), client))
    queue.register("core", APPLY_HANDLER, apply)
    return Core(registry, sources, statuses, sync, tokens, queue)
