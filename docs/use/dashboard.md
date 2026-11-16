# The dashboard

At the end of this page, you can manage teabot's plugins in your browser, with no commands.

The dashboard is at `/dashboard` on your teabot's address, if its operator has turned it on. Ask them for the link.

## Sign in

1. Open the dashboard, and choose **Sign in with Discord**.
2. Discord asks whether teabot may know your name and the servers you are in. Choose **Authorize**.

teabot lists the servers you manage, those where you have **Manage Server**, that it is in. It keeps your name and that list until you sign out, or for a week, and nothing else from Discord.

## Manage a server's plugins

Choose a server. Each plugin shows whether it is on here, what it does, and what outside services it contacts.

- **Turn on** adds its commands to the server, as [`/plugins enable`](plugins.md) does. **Turn off** removes them, and keeps its data and settings.
- Its settings show as boxes, with their current values. Change any, then **Save settings**. Type numbers, and `true` or `false`, as they are, and `null` to clear one.

teabot checks your permissions on every change, as it does for `/plugins`, and the [audit log](audit.md) records each one. A change you may not make says why, and nothing changes.

**Next:** [Who can use what](permissions.md).
