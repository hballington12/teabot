# teabot.core.directory

The member directory (D55, `design/member-directory.md`).

- `rows.py`: a member as stored, read from Discord's member object, and join methods by name.
- `inbox.py`: what a writer receives: gateway events captured on arrival, and a reconcile's pages.
- `gateway.py`: wraps discord.py's parsers for member events, so none is dropped before the writer sees it.
- `writer.py`: one writer per shard, the only writer of member state. A bounded queue, batches of 100 events or one page, and a failed batch retried one entry at a time.
- `apply.py`: compares each entry with the stored row, and writes the row, its history and plugins' event jobs in the writer's transaction. Matches audit log entries and bans to the leaves and changes they explain.
- `reconcile.py`: the reconcile job, paging Discord's member list through the writer, with its guard, and the daily schedule.
- `joins.py`: join methods from Discord's member search.
- `state.py`: each server's directory state, which every answer carries.
- `query.py`: structured filters as SQL with every value a parameter.
- `service.py`: the directory in a bot process, and its daily upkeep: partitions, retention and reconciles.
- `discord_api.py`: what the directory asks Discord, over discord.py's HTTP client.
