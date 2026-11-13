"""How the core's parts fit together, shared by `teapot run` and `teapot.testing`, so tests run the real wiring.

The registry serves the loaded plugins and the admin plugin's built-in groups (`/plugins`, `/audit`,
`/tokens`). Enabling or disabling a plugin queues a command sync, and `/tokens create` checks allow-lists
against every action the registry knows.
"""

from dataclasses import dataclass
from typing import Protocol

from teapot.auth.tokens import Tokens
from teapot.builtin.admin import Admin
from teapot.builtin.tokens import TokenCommands
from teapot.core.audit import AuditLog
from teapot.core.command_sync import CommandApi, CommandSync
from teapot.core.config import ConfigStore
from teapot.core.loader import LoadReport
from teapot.core.queue import Queue
from teapot.core.registry import ActionSource, GuildSource, Registry, sources_from
from teapot.db.pool import Pools


class Client(GuildSource, CommandApi, Protocol):
    """What the core needs from the Discord client."""


@dataclass(frozen=True)
class Core:
    registry: Registry
    sources: dict[str, ActionSource]
    statuses: dict[str, str]
    sync: CommandSync
    tokens: Tokens


def assemble(report: LoadReport, pools: Pools, queue: Queue, client: Client) -> Core:
    statuses = report.labels()
    configs = {p: loaded.plugin.manifest.config for p, loaded in report.loaded.items()}
    admin = Admin(pools.core_db(), statuses=statuses, configs=configs)
    tokens = Tokens(pools.core_db())
    token_commands = TokenCommands(tokens)
    sources = sources_from(report.loaded) | admin.sources() | token_commands.sources()
    sync = CommandSync(pools.core_db(), queue, sources, client)
    admin.on_change = sync.request
    registry = Registry(
        sources, pools=pools, config=ConfigStore(pools.core_db()), client=client, audit=AuditLog(queue)
    )
    token_commands.known = frozenset(registry.actions)
    return Core(registry, sources, statuses, sync, tokens)
