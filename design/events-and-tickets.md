# Plugin events and tickets

Plugins announce what happened as events, other plugins and outside programs react to them, and a tickets plugin is the first to use this: members claim items, handlers accept or reject the claims, and what an accept leads to belongs to whoever listens.

## Why

- **Claims are generic.** A clan linking game accounts, a server handing out keys, and a support desk all have the same shape: items, a member who takes one up, and a handler who settles it.
- **The first user moves off a plugin that did it alone.** The Wise Old Man plugin grew its own claim flow, with its own board, claims, confirm and reject, beside Tea's ranking rules. Tea is retiring that plugin. Its data and rules move into Tea's own program outside teabot, and claiming moves here. The parts that were specific to WOM stay with the program, which keeps the tickets in step:
  - only accounts in the group get a ticket;
  - a rename updates the ticket;
  - evidence such as rank and join date goes in the ticket's body.
- **Ticketing should stop at ticketing.** What follows an accepted claim differs every time: linking an account, giving a role, posting a message, calling a program. A menu of outcomes would grow without end and still miss the next one. Announcing the accept, and letting others react, keeps the plugin small, and lets what follows live in a module or plugin of its own.
- **Outside programs need the same news.** Tea's program reads the accepts from teabot without being a plugin.

## The split

- **In the SDK and the core: plugin events.** A plugin declares the events it emits. Any plugin subscribes to them by name, and the core delivers each one durably, as it delivers Discord events today.
- **In the core: the events feed,** a read action that pages a server's events by cursor, so a program on the service API hears what a plugin hears.
- **A first-party plugin: tickets.** Queues, tickets, claims, a board post, and accept, reject and revoke. It emits events and holds no outcomes.

## Part 1: plugin events

### Declaring and emitting

```python
class Accepted(BaseModel):
    queue: int
    queue_name: str
    ticket: int
    key: str | None
    title: UntrustedText
    claim: int
    claimant: MemberRef

plugin = Plugin("tickets", emits=[Event("accepted", Accepted, "A claim on a ticket was accepted")])

async with ctx.db.transaction() as tx:
    ...
    await tx.emit(Accepted(queue=q, queue_name=n, ticket=t, key=k, title=title, claim=c, claimant=m))
```

- **`Plugin(emits=[...])`** declares each event: a name, a payload model and a line saying what it means. An event's full name is `<plugin>.<name>`, such as `tickets.accepted`. Each event has a model of its own, and registration refuses two events sharing one.
- **Payload models** hold only plain JSON fields: strings, numbers, booleans, dates, lists of these, and nested models of these. Registration refuses anything else.
  - A field holding a member's ID is typed `MemberRef`, the SDK's existing member field, so the core knows which fields name members, and IDs travel as strings in JSON (D29), safe for JavaScript clients. A member ID typed as a plain `int` escapes deletion, which registration can't detect, so the SDK docs warn about it.
  - A field holding text a member wrote is `UntrustedText`, as in action outputs.
- **`tx.emit(payload)`** emits inside the plugin's transaction, so the event exists exactly when the change that caused it commits.
  - The model's type picks the declared event, and emitting an undeclared model raises.
  - One transaction emits at most 100 events, and `tx.emit` raises past that, so a bulk change emits in batches.
  - A payload is at most 8 KB as JSON, and `tx.emit` raises past that, since `UntrustedText` has no length of its own.
- **The core records who caused each event** as `by`, a member ID, from the transaction's `started_by`, which actions and jobs already carry, as `core.jobs.started_by` does. It is empty for the system. So a payload never carries its own actor field.

### How an emit reaches the core

Plugin transactions run as the plugin's own database role, which has no rights on `core` (D9). Each plugin's schema already has functions the migrator creates for it, with the plugin's ID written into their body, which `tx.schedule` and `tx.send` call. `emit_event` is one more of these.

- **The source is fixed** by the function's body, so a plugin can't emit under another's name.
- **The server comes from the connection's `teabot.guild_id` setting,** which the plugin's connection already sets, so a plugin can't emit into another server. This differs on purpose from `schedule_job` and `queue_post`, which take the server as an argument. The function raises when the setting is empty, as on a connection with no server.
- **The function inserts the event row.** The transaction's first emit also queues one core job, `deliver_events`, keyed by the transaction's ID, and later emits in the same transaction find it queued already. The job delivers every event its transaction wrote. So an accept that rejects ninety claims queues one delivery, not a hundred.
- **`deliver_event` fans out in Python,** as Discord events do today. For each of its events, it queues one job per plugin that subscribes and is enabled in that server, from the handlers of the plugins its process loaded. No table of subscriptions is kept. One edge case is accepted: if processes ever run with different plugins loaded, as rolling restarts (D15) would allow, a delivery run by a process without a subscriber skips it. Every process loads the same plugins today. If out-of-process plugins arrive, each process records its subscriptions on its `core.processes` row, and delivery fans out from their union.

### Subscribing

```python
@plugin.on_event("tickets.accepted", Accepted)  # the subscriber's own copy of the model
async def accepted(ctx: Ctx, event: Received[Accepted]) -> None:
    event.data.claimant  # typed
```

- **`@plugin.on_event("<plugin>.<name>", Model)`** subscribes by name, with no import of the emitting plugin, since plugins never import each other. The handler receives `Received[Model]`, with `id`, `source`, `name`, `at`, `by`, and `data` validated into the model. A payload that fails validation fails the job, which shows in `/admin job_status`.
- **Delivery:**
  - Each subscribing plugin gets each event as a job of its own, `on_event:<plugin>.<name>`, whose payload is the event's ID only.
  - When the job runs, it loads the event row. It skips the event if the row is gone, or the plugin is no longer enabled in that server. So a plugin turned back on weeks later never acts on stale news, and member data lives only in the event row.
  - A subscriber job runs with no `started_by`, as the system.
  - A subscriber job has 13 attempts, with the queue's doubling back-off, which spans about two hours. So a Discord or downstream outage of that length loses nothing. Discord events keep their 3 attempts, since they are about a moment, and the comment beside each limit says why they differ.
  - A job that runs out of attempts shows as failed in `/admin job_status`. New with this work, the server's log channel gets one line naming the event and the plugin, so a lost event is seen.
- **At least once.** A retry can deliver one event twice, so a handler that changes something checks `event.id` first, or makes the change idempotent. The SDK docs say so on `on_event`.
- **Order, per thing.** Jobs run in any order, and a retry can run after a later event's job. So:
  - An emitter locks the row of the thing an event is about before it emits, so for one thing, such as one ticket, a higher event `id` is always later. The event ID sequence is created with `CACHE 1`, so a later lock holder never draws a lower ID. The SDK docs say so, and each plugin's docs name the thing each event is about.
  - A subscriber keeps the last event `id` it applied for each thing, and drops an older one. So an `accepted` retried after a `revoked` changes nothing.
  - Across different things there is no order.
- **A plugin subscriber relies on the payload alone.** A plugin can't read another plugin's state, since plugins share no tables or calls (D9). So an emitter puts in its payload what a subscriber needs to act. Only an outside program, on the service API, also reconciles through read actions (Part 2).
- **Notifications, not hooks.** A handler hears what has already happened. It can't veto or change it, and the emitting plugin never waits for it. A check that has to come before a change belongs to the plugin making the change.
- **Handlers run as the system,** with no member's grant. They change what a plugin may change on its own: its tables, its labels and its posts. A plugin whose reaction should change roles writes labels, and role rules turn them into roles under their own grant and cap. `ctx.labels.replace_all` replaces a whole server's labels, and labels go stale after their freshness window. So such a plugin keeps its own table of who should hold what, writes it in full, and rewrites it on a recurring job.
- **A subscription to an event no loaded plugin declares** is allowed and does nothing, so a plugin can subscribe to an optional one. teabot logs a warning when it loads its plugins, naming the event.
- **When both plugins are loaded,** teabot compares the subscriber's model with the emitter's declared model as it loads them, and logs a warning naming a field the subscriber needs that the emitter doesn't send. `teabot check` reads one plugin's files without loading any, so the check happens at load.

### Contracts

- **An event's name and payload are the emitting plugin's public API.** The plugin snapshot test records each declared event's name and JSON schema beside its actions and jobs, so a change shows in review.
  - A subscriber's model ignores fields it doesn't know, which is pydantic's default, and must never forbid extra fields. So adding a field, required or optional, is compatible.
  - Removing a field, retyping it, making it optional or nullable, or renaming an event, is a breaking change for its subscribers, in the plugin's changelog.
- **Each plugin's docs page** lists its events, as it lists its actions.
- **Few events, added on demand.** Each one is a promise to subscribers, so a plugin declares the events a subscriber needs, and adds more when one asks.

### Storage

- **`core.events`:**
  - one row per event, with an `id` that only grows, and `tx_id`, the `xid8` of the transaction that wrote it;
  - the server, source, name, payload and time;
  - `member_ids`, a `teabot.member_id[]` filled from the payload's `MemberRef` fields, so `teabot users delete` deletes the rows that name a member;
  - `by`, anonymised to 0 when its member's data is deleted, as one more step beside the audit log's, so deleting the actor never deletes the event;
  - `untrusted`, the paths of the payload's `UntrustedText` fields, recorded at emit, so the feed marks them even after the emitter is gone;
  - removed with the rest of a server's data when the bot leaves it for good, in the core's server purge;
  - each row is kept for 30 days, then deleted;
  - indexes on `(guild_id, tx_id, id)` for the feed, a GIN index on `member_ids` for deletion, and one on the time for pruning.

### Anonymising a plugin's member column

`teabot users delete` deletes a plugin's rows that name the member through a `teabot.member_id` column. Some facts must outlive a member who only took part in them, such as who accepted a claim. A second domain type, `teabot.member_actor`, marks a column that the deletion sets to null instead, keeping the row. The migrator refuses one declared `NOT NULL`. Its name keeps it apart from the SDK's `MemberRef`, which is any member field. This is a small addition beside the existing one, in the core's member data step.

## Part 2: the events feed

`admin.events`, a core read action, offered on MCP and the service API.

- **Input:**
  - `after`, an opaque cursor, empty to start;
  - `names`, up to ten event names, or all when left out;
  - `limit`, up to 100.
- **Output:**
  - the server's events after the cursor, in feed order, each with `id`, `source`, `name`, `at`, `by` and `data`, as a plugin's `Received` has them, and the cursor to pass next;
  - fields typed `UntrustedText` are marked untrusted, as action outputs are on MCP.
- **Needs:** Manage Server, since events can name members and what they did.
- **No event is skipped.**
  - The feed orders events by `(tx_id, id)`, and returns only rows whose `tx_id` is below `pg_snapshot_xmin(pg_current_snapshot())`.
  - Every transaction below that point has finished, so nothing can later appear before the cursor. The cursor encodes the last `(tx_id, id)`.
  - A long write transaction anywhere on the database cluster holds the feed back until it finishes, since only transactions that wrote anything have an ID. The feed is late then, never wrong.
  - `(tx_id, id)` order guarantees no gaps, not commit order, since a transaction can get its ID before it waits on a lock. So a program orders by `id` per thing, as a plugin subscriber does.
- **Reads are audited** as every read action is, one row per call in `core.audit_reads`, which is partitioned by day. A program polling every ten seconds writes about 8,640 rows a day.

**Events are news, and state lives at the source.** Rows go after 30 days, and a program down longer than that misses news. So a program never builds its state from events alone. It reads the source's state through read actions, such as `tickets.list`, when it starts, after a gap longer than the feed keeps, and once a day. In between, events tell it when to look.

## Part 3: the tickets plugin

### Queues

A queue is one kind of ticket, set up by an admin with `tickets.queue_add`, and changed with `tickets.queue_edit`:

| Setting | What it is |
|---|---|
| `name` | Such as "Link your account" |
| `channel` | Where its board is posted |
| `claimers` | Roles that may claim. Everyone when left empty |
| `handlers` | Roles that may create, accept, reject, revoke, cancel and read tickets. Members with Manage Server always may. A program acts as its token's member, so that member is a handler |
| `per_day` | How many new claims a member may make in the queue each day, withdrawn ones included, 10 by default |
| `handlers_channel` | Optional. Each new claim is posted there with Accept and Reject buttons for handlers, and the post is edited once it is settled |

- A queue holds up to 10,000 open tickets, and a ticket up to 10 waiting claims.
- `tickets.queue_remove` deletes the queue and its tickets, after a plan. It emits nothing, and leaves in place whatever subscribers built from its accepts. An outside program sees the queue go through `tickets.list`.
- Commands are visible to every member, and the plugin checks the queue's roles itself, since Discord's own command permissions can't follow per-queue roles. Per-command permission overrides (D19) are the place to narrow this later.

### Tickets and claims

- **A ticket:**
  - an `id` and its queue;
  - a `title` and an optional `body`;
  - an optional `key`, the creator's own reference, such as a game account's ID, unique within the queue among the tickets it keeps;
  - its `state`, `open` or `closed`, and for a closed ticket, its `resolution`: `accepted` or `cancelled`;
  - `updated_at`, set by every change to the ticket or its claims.
- **A claim:**
  - its ticket and the member who made it;
  - an optional `note`, such as "my alt from 2019";
  - its `state`: `waiting`, `accepted`, `rejected`, `withdrawn` or `revoked`;
  - `settled_by`, a `teabot.member_actor`, and when, with the reason given.
- **One waiting claim per member and ticket,** enforced by a unique index.
- **Competing claims wait together.** A handler sees them side by side.
  - Accepting one closes the ticket as `accepted`, and rejects the others with the reason "another claim was accepted".
  - Each of those rejections emits `tickets.rejected`, within the cap of 10 waiting claims.
- **Rejecting a claim** leaves the ticket open, for others or for the same member to claim again.
- **Cancelling a ticket** rejects its waiting claims with the reason "the ticket was cancelled", each with `tickets.rejected`. Cancelling a closed ticket is refused.
- **Revoking an accept:** `tickets.revoke(ticket, reason?)` undoes a wrong accept. It marks the accepted claim `revoked`, reopens the ticket, and emits `tickets.revoked` with the claim and the claimant, so a subscriber undoes what it did. An accepted ticket is never reopened any other way. It also works on an accepted ticket whose claim is gone, such as after the claimant's data was deleted, so no ticket stays closed for good.
- **Concurrency:**
  - Every write to a ticket or its claims locks the ticket's row first: claiming, withdrawing, accepting, rejecting, revoking, cancelling and updating. So a claim can't land on a ticket an accept just closed, and the cap of waiting claims is counted under that lock.
  - A call touching several tickets locks them in ascending ID order, so concurrent calls never deadlock.
  - Counts across a queue, `per_day` and the cap of open tickets, are taken under a lock on the queue's row, since two claims by one member on different tickets take different ticket locks.
  - One `accept` call naming two claims on the same ticket is refused.

### Actions

Every action works on every door: slash command, MCP, the service API and the site, as any teabot action does.

- **Creating:**
  - `tickets.create(queue, titles, keys?, bodies?)` takes up to 25 tickets, as lists in the same order, since action inputs are flat and a list off slash commands holds 25. It is offered on MCP, the service API and the site.
  - A ticket whose key already exists in the queue, in any state, updates that ticket's title and body, and never reopens it. So a program keeps its tickets in step by key, and can repeat a call safely.
  - It returns each ticket's ID, state and outcome: `created`, `updated` or `unchanged`. A program sends only tickets that changed, so a sync stays small in the audit log.
  - A cancelled ticket's key is free again once the ticket is deleted, 90 days after closing.
- **Maintaining:** `tickets.cancel(ticket, reason?)` cancels a ticket, and `tickets.reopen(ticket)` reopens a cancelled one. Both are for handlers.
- **Claiming:**
  - `tickets.claim(ticket, note?)`, where the `ticket` option autocompletes as the member types over the open tickets of every queue they may claim in, with each queue's name beside the title;
  - `tickets.withdraw(claim)`;
  - `tickets.mine` lists your claims and their states.
- **Handling:**
  - `tickets.waiting(queue?)` lists waiting claims, oldest first, with competing claims side by side, and each ticket's body as evidence;
  - `tickets.accept(claims)` and `tickets.reject(claims, reason?)` take up to ten claims;
  - `tickets.revoke(ticket, reason?)`.
- **Reading:** `tickets.list(queue, state?, key?, claimant?, changed_since?, page)` pages tickets with their claims, for handlers, since it shows other members' claims and the evidence in ticket bodies. `tickets.waiting` needs the same. It is the source of state that programs reconcile against, and `changed_since` keeps a daily reconcile, or one after a gap longer than the feed keeps, to the tickets that changed.
- **The board:**
  - `tickets.post(queue)` posts the queue's board in its channel: its name, a line on how it works, the count of open tickets, and buttons. The count is refreshed by an edit at most once a minute.
  - The **Claim** button opens a form with one text field. A name that matches one open ticket, ignoring case and spaces, claims it. Otherwise the reply names up to five closest open tickets, and `/tickets claim` searches them all as the member types, since a reply can't carry buttons. So the board never lists hundreds of tickets.
  - The **My claims** button shows `tickets.mine`.
- **Search** matches titles containing what was typed, ignoring case and spacing, in SQL. When nothing contains it, the plugin ranks the queue's titles by similarity in Python. 10,000 titles is a small list, so this needs no database extension.

### Accepting has no plan

`tickets.accept` is a write, not a destructive action with a plan. What an accept leads to belongs to its subscribers, which the tickets plugin can't see, so it has no consequences of its own to show. The handler is settling who a ticket belongs to, and `tickets.revoke` undoes a mistake. A subscriber whose reaction is weighty puts its own guard on it. Labels that change roles pass through role rules, which hold a run above its cap for an admin.

### Events

Three, to start, each about one ticket:
- `tickets.accepted`
- `tickets.rejected`
- `tickets.revoked`

Each payload holds what a subscriber needs to act on it alone:
- the queue's ID and name;
- the ticket's ID, key and title;
- the claim's ID and note, and the claimant, all nullable in `revoked`, whose claim can be gone;
- for `rejected` and `revoked`, the reason.

The handler is the event's `by`. More events, such as `claimed` or `cancelled`, are added when a subscriber asks for them. An accept of ten claims emits at most 10 accepts and 90 rejections, within the cap of 100.

### What it does not do

- It changes no roles, links nothing, and posts nothing beyond its board and its replies. Those are for subscribers.
- It doesn't message claimants when a claim is settled. `tickets.mine` shows it, and a subscriber can send a message.

### Data and privacy

- **Accepted tickets,** with their claims, are kept while their queue exists, since an accept is a lasting fact that programs reconcile against.
- **Cancelled tickets** are deleted 90 days after they close, and every claim not accepted, on any ticket, 90 days after it settles.
- **Member data:**
  - Every claim's member is a `teabot.member_id` column, so deleting a member's data deletes their claims.
  - `settled_by` is a `teabot.member_actor` column. Deleting a handler empties it, and the claims they settled stay.
  - An accepted ticket whose claimant's data was deleted stays closed as `accepted`, and `tickets.list` shows it with no claimant.

## How Tea uses it

- **A queue,** "Link your account":
  - `claimers` everyone, and `handlers` Tea's staff, with the handlers' channel set;
  - its board in the link channel.
- **Tea's program** is outside teabot. On a timer, it calls `tickets.create` with one ticket per clan account, keyed by WOM's player ID.
  - The account's name is the title, and its rank and join date are the body. A rename updates the title.
  - When an account leaves, the program cancels its ticket. When it rejoins, the program reopens it, since `create` never reopens. After a revoke, which reopens a ticket, it cancels the ticket again if the account has left.
- **A member** presses Claim on the board, types "gren clog", and picks "Green Clog".
- **Staff** see each claim in the handlers' channel, and accept or reject it there, or revoke a wrong one. The program reads `tickets.accepted` and `tickets.revoked` from the feed, links or unlinks the account, and reconciles with `tickets.list` daily.
- **Roles:** the program pushes labels through external labels, a separate design. teabot's role rules turn them into roles, and hold large changes for an admin.

## Out of scope here

- **External labels,** for a program to write labels, and the **application credential** a program needs to act without a person's token expiring. These are separate designs.
- **Tickets members open themselves,** as for a support desk. A queue where members create tickets needs an opener column, the opener's rights, and rules on keys and on deleting member-written text. They are added when such a queue is needed.
- **An automations plugin,** for admins to configure "on this event, do that" without code. It would build on these subscriptions, once something needs it.
- **Moving `labels_changed` onto plugin events.** It could become a core-declared event under the same mechanism, which would leave one event path, with the roles plugin as the first plugin subscriber. That is the next step once this ships.

## Order of work

1. Plugin events in the SDK and the core, with `teabot.member_actor`, the snapshot and the docs.
2. The events feed.
3. The tickets plugin, with its docs page, and its events as the first real use of both.
