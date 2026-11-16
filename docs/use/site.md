# Your teabot's site

At the end of this page, you can turn your server's plugins on and off, and change their settings, in your browser, with no commands.

Every teabot with a public address has its own site there. For the [official Teabot](https://teabot.tea-osrs.com/), that is `https://teabot.tea-osrs.com/`. For another teabot, ask its operator for the address.

## Sign in

1. Open the site, and choose **Sign in with Discord** at the top.
2. Discord asks whether teabot may know your name and the servers you are in. Choose **Authorize**.

teabot keeps your name and the list of servers you manage, those where you have **Manage Server**, until you sign out, or for a week. It keeps nothing else from Discord.

## Choose a server

At the top, choose one of your servers that teabot is in. The site remembers it until you choose another.

## Turn plugins on and off

Open **Plugins**. Each plugin shows what it does and, for the server you chose, whether it is **On** or **Off**. Press it to switch.

- Turning a plugin on adds its commands to the server, as [`/plugins enable`](plugins.md) does. Turning it off removes them, and keeps its data and settings.
- Open a plugin for its page, which also shows what outside services it contacts and its settings.

## Change a plugin's settings

On a plugin's page, its settings show as boxes, with their current values. Change any, then **Save settings**. Type numbers, and `true` or `false`, as they are, and `null` to clear one.

teabot checks your permissions on every change, as it does for `/plugins`, and the [audit log](audit.md) records each one. A change you may not make says why, and nothing changes.

**Next:** [Who can use what](permissions.md).
