# Channels and permissions

Admins and AI assistants see every channel's permissions, and the server as any set of roles sees it, as Discord's "View server as role" shows. It is built in `src/teabot/builtin/permissions.py`.

## Why

- Discord shows a channel's overwrites one channel at a time, and "View server as role" only inside its own app.
- An AI assistant asked "who can see #staff?" or "what can Raiders do here?" has no way to answer.

## Source

Everything is computed live from the gateway's cache, which teabot already holds: roles, channels, categories and their overwrites. Nothing is stored, and no Discord request is made.

## Actions

Both need Manage Server, are read-only, are offered to AI assistants and the service API, and are recorded among the audit log's look-ups (D24). Permissions are named as discord.py names them, once each, with View Channel as `view_channel`.

- **`admin.channels`:** every category and channel in Discord's order, each with its type, its category, whether it is synced with its category, and its permission overwrites: for each role or member, the permissions allowed and denied, by name.
- **`admin.view_as`:** for one or more roles, as Discord's view-as-role combines them, every channel visible or hidden, and for a visible one the permissions those roles have there.

## The algorithm

As Discord computes it, for a set of roles, which always includes @everyone:

1. The base is the union of the roles' server permissions.
2. Administrator in the base grants everything, in every channel, and stops here.
3. In a channel, the @everyone overwrite applies: its denies, then its allows.
4. Then the roles' overwrites together: the union of their denies, then the union of their allows.
5. For a member, their own overwrite applies last, denies then allows. View-as-role has no member, so it skips this.
6. Without View Channel, every other permission in that channel is lost.
7. In a text channel, without Send Messages, the permissions that depend on it are lost: embedding links, attaching files, mentioning everyone, and sending text-to-speech messages.
8. The server's owner has every permission everywhere. View-as-role never stands for the owner.

A category's overwrites govern its channels only through synced channels' copies, so each channel is computed from its own overwrites, as Discord does.
