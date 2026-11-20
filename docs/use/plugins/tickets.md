# Tickets

Keep a queue of items members claim, such as game accounts, keys or slots, and let handlers accept or reject each claim. Tickets stop at ticketing: what follows an accepted claim, such as linking an account or giving a role, belongs to another plugin or a program that listens for the plugin's events. Turn it on with `/plugins enable plugin:tickets`.

## Make a queue

```text
/tickets queue_add name:Link your account channel:#link handlers_1:@Staff handlers_channel:#staff-claims
```

| Option | What it is |
|---|---|
| `name` | The queue's name, up to 100 characters. |
| `channel` | Where its board is posted. |
| `handlers_1` to `handlers_10` | Roles that may create tickets, accept, reject and revoke claims, and read the queue. Members with Manage Server always may. |
| `claimers_1` to `claimers_10` | Roles that may claim. Everyone, if left out. |
| `per_day` | How many claims a member may make in the queue each day, withdrawn ones included. 10 if left out. |
| `handlers_channel` | Where each new claim is posted for handlers, with **Accept** and **Reject** buttons. |

`/tickets queue_edit queue:1` changes a queue; what you leave out stays as it is. `/tickets queues` lists the server's queues with their open tickets and waiting claims. `/tickets queue_remove queue:1` deletes a queue with its tickets and claims, after a [plan](../confirming.md).

## Create tickets

Handlers, and programs acting for one, create tickets with the AI assistant tool `tickets_create`, which also works through the service API and on the site. It takes up to 25 at once:

| Input | What it is |
|---|---|
| `queue` | The queue's number. |
| `titles` | Each ticket's title, such as an account's name. |
| `keys` | Your own reference for each ticket, in the same order, such as an account's ID. |
| `bodies` | Each ticket's details, in the same order, such as evidence handlers see. |

- **A key names one ticket in its queue, whatever its state.** Creating a ticket with a key the queue already has updates that ticket's title and body, and never reopens it. So a program keeps its tickets in step by repeating the same call.
- **It reports each ticket** as `created`, `updated` or `unchanged`, with its number and state, so a program sends only what changed.
- A queue holds up to 10,000 open tickets.

`/tickets cancel ticket:12` closes an open ticket and rejects its waiting claims. `/tickets reopen ticket:12` opens a cancelled one again.

## Post the board

```text
/tickets post queue:1
```

The board shows the queue's name, a line on how it works, and how many tickets are open, refreshed a minute after they change. It has two buttons:
- **Claim** opens a form for what the member is claiming. A name that matches one open ticket, ignoring case and spaces, claims it. Otherwise teabot names the closest open tickets.
- **My claims** shows the member's claims and how they stand.

Posting again replaces the board. The board never lists every ticket, so a queue of hundreds stays readable.

## Claim a ticket

```text
/tickets claim ticket:Green Clog note:my main since 2021
```

The `ticket` option searches the open tickets of every queue you may claim in as you type. A handler then accepts or rejects the claim.

- One waiting claim per member on a ticket, and up to 10 waiting claims on a ticket.
- `/tickets mine` lists your latest claims. `/tickets withdraw claim:7` withdraws one still waiting.

## Settle claims

```text
/tickets waiting queue:1
/tickets accept claims_1:7
/tickets reject claims_1:8 reason:not your account
/tickets revoke ticket:12 reason:accepted the wrong member
```

- `/tickets waiting` lists a queue's waiting claims, oldest first, with competing claims side by side and each ticket's details as evidence. The handlers' channel shows the same, with buttons.
- **Accepting** a claim closes its ticket, and rejects the ticket's other waiting claims, with the reason "another claim was accepted". Up to ten claims at once, one per ticket.
- **Rejecting** a claim leaves its ticket open, for others or for the same member to claim again.
- **Revoking** undoes a wrong accept: the claim is marked revoked and the ticket reopens. It also works on an accepted ticket whose claimant's data was deleted.
- Accepting has no plan. What an accept leads to belongs to whoever listens for it, and `/tickets revoke` undoes a mistake. A plugin that turns accepts into roles goes through role rules, which hold large changes for an admin.

## Read a queue

The AI assistant tool `tickets_list` pages a queue's tickets with their claims, for its handlers. It filters by `state`, `key`, `claimant` and `changed_since`, such as `2026-11-20T09:00:00Z`. A program following a queue reconciles against it: when it starts, once a day, and after a gap longer than events are kept.

## Events

Each is about one ticket, so for one ticket a later event has a higher `id`. Plugins subscribe to them, and programs read them with [`admin_events`](../ai.md#follow-a-servers-events).

| Event | When | Payload |
|---|---|---|
| `tickets.accepted` | A claim was accepted, closing its ticket. | `queue`, `queue_name`, `ticket`, `key`, `title`, `claim`, `note`, `claimant` |
| `tickets.rejected` | A claim was rejected, by a handler, because another was accepted, or because its ticket was cancelled. | The same, and `reason` |
| `tickets.revoked` | An accept was undone, reopening its ticket. | The same as rejected; `claim`, `note` and `claimant` are empty when the claim is gone |

## Who can use it

| Command | Needs |
|---|---|
| `/tickets queue_add`, `/tickets queue_edit`, `/tickets queue_remove` | Manage Server |
| `/tickets queues` | nothing |
| `tickets_create`, `/tickets cancel`, `/tickets reopen`, `/tickets post` | a handler role of the queue, or Manage Server |
| `/tickets waiting`, `tickets_list`, `/tickets accept`, `/tickets reject`, `/tickets revoke` | a handler role of the queue, or Manage Server |
| `/tickets claim` | a claimer role of the queue, when it has any |
| `/tickets mine`, `/tickets withdraw` | nothing |

Commands are visible to every member, and teabot checks the queue's roles when one is used, since Discord's own command permissions can't follow roles set per queue. The board's Claim button runs `/tickets claim_from_board`, which only the button reaches.

## Data

- Accepted tickets, with their claims, are kept while their queue exists.
- Cancelled tickets, and claims that were rejected, withdrawn or revoked, are deleted 90 days after they closed or were settled.
- Deleting a member's data deletes their claims. A handler's deletion keeps the claims they settled, without their name.

## Settings

None.

## For AI assistants

The tools are `tickets_queue_add`, `tickets_queue_edit`, `tickets_queue_remove`, `tickets_queues`, `tickets_create`, `tickets_cancel`, `tickets_reopen`, `tickets_list`, `tickets_post`, `tickets_claim`, `tickets_withdraw`, `tickets_mine`, `tickets_waiting`, `tickets_accept`, `tickets_reject` and `tickets_revoke`.

**Next:** [Troubleshooting](../troubleshooting.md).
