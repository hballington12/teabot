# Member directory

teabot keeps a directory of every server's members, with their history, so admins, AI assistants and plugins can query it (D55). The design was reviewed until it converged. The directory, its sync and the admin tools are built, in `src/teabot/core/directory/` and `src/teabot/builtin/members.py`. The site's Members page and plugins' `ctx.members` follow. Channels and permissions are a separate design, [server-permissions.md](server-permissions.md).

## Why

- Discord forgets who left a server, who was banned, and when a member's roles changed.
- Its member list cannot be filtered like a table, counted by role or join method, or combined with a plugin's own data.
- Today teabot's tools ask Discord live, which costs a request per page and keeps nothing.

## Data

Tables in `core`, all carrying `guild_id`, so server deletion (D49) and member deletion (D11) cover them. Plugins never read them directly (see [Plugins](#plugins)).

- **`core.members`**, one row per member per server, current state, keyed by (`guild_id`, `user_id`):
  - `user_id` (`teabot.member_id`), `name` (username), `global_name` (display name), `nickname`, `bot`.
  - `role_ids bigint[]`.
  - `joined_at`, which may be null, as Discord allows; `premium_since` (boosting); `timed_out_until`, compared with the time when filtered, since a timeout ends with no event; `pending` (membership screening); `flags`, Discord's member flags, such as did-rejoin and completed-onboarding.
  - `join_source`, Discord's raw `join_source_type` number, mapped to a name in code so a value Discord adds is kept; `source_invite_code`; and `inviter_id`, a plain `bigint`: a copy of the latest join's method, for filtering.
  - `left_at`, null while a member: a member who leaves keeps their row.
  - `observed_at`: when the bot received what this row says. Removing a deleted role from every row leaves it as it was.
  - Indexes lead with `guild_id`: (`guild_id`, `left_at`) and (`guild_id`, `joined_at`); and one on `user_id`, for a deletion request across every server. One server is at most a few hundred thousand rows, so role and name filters scan its rows; a composite GIN or trigram index is added only where measurement shows the need.
  - Account age is not stored. A user ID grows with time, so "account created between" is a range on `user_id`, which the primary key serves.
- **`core.member_events`**, the history, partitioned by month: levelling and reaction-role bots, and teabot's own bulk role changes (D21), can write thousands of rows a day in a large server, and a month is dropped whole, as `core.audit_reads` drops its days (D24).
  - `user_id`, `kind`, `at`, `actor_id` (who did it, when Discord says), and a `detail` object holding, per kind:
    - `joined`: `join_source`, `source_invite_code`, `inviter_id`, this join's method, since a member may rejoin by another way.
    - `left`; `kicked` and `banned`, which replace the member's `left` row when Discord's audit log entry or ban event matches it, whichever arrives first, within a minute; `unbanned`. Bans are recorded only for a member the directory knows. Members pruned together stay `left`, since a prune's audit entry names no one.
    - `timeout`: until when, or its removal.
    - `roles`: `added` and `removed` role IDs.
    - `nickname`: the old nickname and the new one. A nickname belongs to the server. Usernames and display names belong to the user, so their changes are not kept: the row holds only the current ones.
    - `role_deleted`: one row for the server, with no `user_id`, holding the role's name and the IDs of the members who held it, so "who had it" stays answerable.
  - `reason`, from Discord's audit log entry, for kicks, bans and timeouts: untrusted text (D23).
  - Teabot's own changes, such as a bulk role change (D21), name the member who asked: teabot tells Discord's audit log "via teabot: <action>, for member <id>", and the writer takes that member as the actor, not the bot.
  - `source`: `event`, from the gateway as it happened; or `reconcile`, found by a reconcile, with `since` as well as `at`, so tools say "between since and at".
  - Indexes on (`guild_id`, `at`), (`guild_id`, `user_id`, `at`) and `user_id`.
- **`core.directory_state`**, one row per server: when its history starts, whether its backfill is done, its last reconcile, whether events were dropped since, whether its last reconcile's guard stopped it, and the join-method lookup's cursor.
- **Retention:** one period, the operator's, `TEABOT_DIRECTORY_RETENTION_DAYS`, a year by default; the official Teabot sets 30 days, as its privacy policy says for its other records. Whole months of history are dropped once older, and members who left that long ago are deleted in batches by the daily maintenance.
- **Size:** an operator may set a member-count ceiling, `TEABOT_DIRECTORY_MEMBER_LIMIT`; there is none by default. Above it, the directory is off for that server: its rows are kept as they were, and the tools say the directory is off. Back under it, the server is backfilled again.

## Keeping it current

### Gateway events

- **One way in.** discord.py drops some member events before any handler sees them, which handlers alone cannot fix: an update for a member it has not cached, which is most members, since teabot does not cache every member (D25); a join for a member already cached; and a deletion of a role it has not cached. The client therefore wraps discord.py's parsers for member add, update and remove, ban and unban, role delete, and audit log entry. Each wrapper puts its event on the shard's writer queue at the moment it arrives, so the queue holds every event in receipt order. discord.py builds its parser table from bound methods when the client is made, and the gateway reads that table, so teabot replaces the table's entries after the client is built.
- **Checked, not pinned.** A test checks that the parser table has those entries, so a discord.py release that moves them fails teabot's own tests first. If they are ever missing at startup, teabot logs an error and relies on the reconcile alone.
- **One writer per shard, the only writer of member state.** One task drains its shard's queue in order, up to 100 events at a time, into one transaction. A shard has one process (D40), and a resumed session replays missed events in order. If a batch fails, its events are retried one by one, so one bad event cannot stall the shard; that one is logged and skipped.
- **One diff.** The writer compares each event with the stored row: an update carries the member's full role list and names. The difference is the source of the history's events and of the plugins' `on_member_join`, `on_member_leave` and `on_member_roles`.
- **Atomic.** A batch's rows, history and plugin event jobs commit in one transaction, so none is written without the others.
- **Gateway events reach plugins; late ones only on request.** The backfill fires nothing, or it would fire a join for every existing member. Changes a reconcile finds in a gap, such as joins while the bot restarted, are delivered as late events, with `since`, and only to handlers that ask for them: an auto-role plugin catches joins a deploy missed, and a welcome plugin never greets someone hours late.
- **Known imprecision in a gap.** Between a fresh session and its server's reconcile, an update is compared with a row that may be stale, so a change made while the bot was down can be recorded as `event`. A join for a member still marked present means their leave was missed: the writer records that `left`, from the reconcile, before the `joined`.
- **A member with no row yet**, while a server's backfill has not finished: a join or leave writes its row and fires its event as usual. A role change falls back to discord.py's cached copy of the member, when there is one, as today; with none, the row is written with no event. Once the backfill is done, every member has a row, and the fallback is unused. So `on_member_roles` reaches every member only where the directory runs: while a server's backfill runs, or above the ceiling, it reaches cached members, as today.
- **A deleted role** is removed from every row's `role_ids` in one statement.
- **Kicks and actors.** Discord's audit log entry events arrive by push, with the moderation intent teabot's default intents include, when the bot has View Audit Log. An entry turns the matching `left` into `kicked`, and fills `actor_id` on role changes, timeouts and nickname changes: who gave a member a role. Without the permission, these stay `left` and unattributed.
- **Bounded.** A shard's queue holds at most 10,000 entries, an event or a reconcile's page each. A gateway wrapper never waits: when the queue is full, as in a database outage, it drops the event and marks the shard. A reconcile's page waits for room, and is never dropped. When the database is back, a marked shard's servers are reconciled, as after a fresh session, and record that events were dropped.
- **Drained on shutdown:** the client's close waits up to ten seconds for each writer to empty its queue. Anything left counts as dropped.

### Reconcile

- **When:** for each server once a day, spread across the day, unless it was reconciled in the last 24 hours. Also, for a shard's servers, when the shard starts a fresh session rather than resuming, which every deploy does, since events are lost while the bot is down; for a server that becomes available again after a Discord outage; for a server whose events were dropped; and for a server that re-adds the bot within the grace period (D49). A shard's fresh session spaces its servers' reconciles two seconds apart, and at most two run at once in a process, so the other workers stay free for plugins' jobs; the rest wait as pending jobs. Their history's `since` is the server's last reconcile, the latest time its copy is known to have been complete.
- **A page at a time, through the writer:** it pages Discord's documented member list, `GET /guilds/{id}/members`, 1,000 at a time. Discord returns members in user ID order, so each page covers a known range of IDs. The reconcile puts each page on the shard's writer queue, and the writer compares that range when it reaches it, after every event received before it: new members, changed roles and nicknames, and members in the range missing from the page, who left. A queued join is therefore applied, and fires its plugin event, before the comparison could record it. A page changes only rows observed at least a minute before its request started, so an event received since wins over it, and a page served a little behind the gateway cannot undo it. A page is one short transaction, so no server's comparison holds up its shard's other servers.
- **Rejoins in a gap:** a member whose `joined_at` changed left and joined again while the bot was not watching: a `left` and a `joined`, both from the reconcile.
- **Progress:** the cursor is the job's progress (D31), so a crash resumes at the next page. Nothing is staged. It never uses discord.py's member cache or `chunk()`, so memory stays small (D25, D43).
- **The guard:** in a server above a few hundred members, the run checks, page by page and at the end, the members it has found against Discord's own member count for the server. When they fall well short, the listing was cut off: the run stops before marking anyone left in what it has not seen, logs a warning and records it in `core.directory_state`. When they match, the leaves are real, and a mass prune, or a re-add after weeks away, is recorded at once. The same count, drifting from the directory's, queues a reconcile between daily runs.
- **Deleted roles:** a role in members' rows that the server no longer has is one `role_deleted` row.
- **Backfill:** a server's first reconcile. It writes rows and no history, and fires nothing. History starts then, which `core.directory_state` records, and every tool says so: members who had already left, and earlier joins and role changes, are unknown.

### Join method

- Discord's member search, `POST /guilds/{id}/members-search`, returns `join_source_type`, `source_invite_code` and `inviter_id` to a bot (S9). It is not in Discord's published docs, so it is used for nothing else, and an operator can turn it off. Before the official Teabot uses it, its rate limits, its delay behind joins and its paging limit are measured, and Discord's Developer Terms on undocumented endpoints are checked.
- **Daily:** with each server's daily reconcile, the search is read newest join first, 1,000 a page, back to the newest join read before, usually one page. The backfill reads it all once. Results go on the `joined` rows and the member rows, only where the row's `joined_at` still matches, so a lookup racing a rejoin never gives the new join the old one's method. Discord answers 202 while it builds a server's search index; the lookup then tries again the next day.
- So join method is never known at the moment of joining: plugins' `on_member_join` does not get it.
- **On demand:** when `admin.members` filters by join method, members joined since the last lookup are looked up first.
- If the search fails, is off, or has nothing, join method is `unknown`, and nothing else is affected. Discord has no join method for very old joins.
- Comparing invites' use counts, the documented alternative, misjudges simultaneous joins, and misses one-use invites and joins from server discovery, so it is not used.

## Reading it

### AI assistants and the service API

- **`admin.members`** lists members with structured filters: roles any, all or none, no roles; joined and account-created ranges; join method, invite code and inviter; name, display name or nickname contains; boosting, timed out, pending; bots; present or left. It sorts, pages and counts, and with `group_by` it counts by role, join method, inviter or join month instead. It needs Manage Server, as Discord's own member settings do.
- **`admin.member_history`** gives one member's, or the server's, events in a date range, with each event's source. It needs Manage Server.
- **`admin.find_members`** keeps its permission, none extra, so any member can find another's ID for an action (D25), and its matching: names that start with the query. The directory answers it, with present members only; until a server's backfill is done, or where the directory is off, Discord's search answers it as today.
- **Before a backfill, or where the directory is off,** the other tools and `ctx.members` say so, with the backfill's progress, instead of answering partially.
- Every answer carries the directory's state: whether the backfill is done, when history starts, the last reconcile, and whether events were dropped since, so an assistant does not present stale or partial data as fact.
- No raw SQL is accepted. Names are untrusted text (D23). Each call is recorded among the audit log's look-ups (D24).
- Permission checks never use the directory, which can lag: they keep using the live cache and Discord (D18).

### Admins in a browser

A Members page on the instance's site (D52), with the same filters and a CSV export, for members with Manage Server. The export is a registry action through the `web` door, so it is audited, and it escapes a cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return, since names are member-written and a spreadsheet would run them as formulas.

### Plugins

- **A typed API in the SDK:** `ctx.members.count(filter)` and `ctx.members.find(filter)`, with the `MemberFilter` that `admin.members` takes, come first, with role changes ([role-changes.md](role-changes.md)). `get(user_id)` and `history(...)` follow when a plugin needs them. Core code runs them for the current server only, so no plugin setting can widen them to other servers.
- **Declared:** a plugin declares that it reads the directory, `Plugin(..., reads=["members"])`, and only then does `ctx.members` work. The hub's catalogue and the site show the declaration, as they show external hosts (D12). It is a declaration, not a sandbox: plugin code runs in the core's process (D5), so the guide and the hub describe it as disclosure, which review checks.
- **SQL views later:** when a plugin needs to join the directory with its own tables in SQL, read-only views follow, behind the same declaration. They are not part of this design, since plugin code can change the setting that holds SQL to one server (S6), which for the directory would expose every server's members.
- **In the SDK guide:** names are untrusted text (D23), and `ctx.members` answers carry the directory's state, as the tools' do.
- **`on_member_roles` changes:** where the directory runs, it fires for every member, where today only members teabot has cached reach it. A plugin in a server with a levelling bot gets many more jobs. The changelog and the guide say so.
- **Late events:** a handler receives changes a reconcile found only when it asks, `@plugin.on_member_join(late=True)`, and then gets `since` with them.
- **Labels:** a plugin that declares `writes=["labels"]` keeps short strings about members in the core, `core.member_labels`, keyed by member ID, which filters match while the plugin is enabled and its data is within its freshness window. The core gives them no meaning. A whole-server replace compares inside one transaction and writes only changed rows.

## Privacy

- The directory keeps data on every member, not only those who use a feature. It keeps server-level history only: joins, leaves, roles and nicknames, never a user's username or display-name history across servers. The instance's privacy policy says so, with its retention period (D52). The directory is part of what D39's privileged-intent justification names, and Discord's Developer Policy on data about members who never used the bot is checked before release.
- A member's deletion request (D11) deletes their directory rows and history in every server, through steps in the core's deletion, and sets `inviter_id` and `actor_id` to 0 where others' rows name them, which scans every partition: rare, and accepted. A member who asks while still in a server reappears at their next event or reconcile, with no history before it: the directory reflects current membership, as Discord's own list does. D11 records this, and the guide says so.

## Decisions this changes

When built: D6 and D45 (the `reads=` declaration, `ctx.members`, and `on_member_roles` firing for every member), D11 (the core keeps per-member data, and the reappearance rule), D25 (member lookups come from the directory, not the gateway's member search; full member lists are paged by REST into Postgres, never into memory), D39 (the directory in the intent's justification), D52 (the Members page), and a new decision for the directory itself.
