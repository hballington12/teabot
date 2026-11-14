# Turn on plugins

At the end of this page, the plugins you want are on in your server, with the settings you want.

A **plugin** adds a set of commands to teabot, such as `/giveaways`. Every plugin is off in your server until you turn it on. These commands need **Manage Server**.

## See the plugins

```text
/plugins list
```

teabot lists each plugin, and whether it is on here:

```text
announcements enabled
giveaways disabled
```

A plugin may say `not loaded`, with a reason. That is for the operator to fix, and the plugin cannot be turned on until they do.

## Turn one on

```text
/plugins enable plugin:giveaways
```

teabot replies `giveaways is now enabled here.`, and the plugin's commands appear under `/giveaways`. Discord can take a minute to show new commands. If they do not appear, reload Discord with ++ctrl+r++, or ++cmd+r++ on macOS.

## Turn one off

```text
/plugins disable plugin:giveaways
```

Its commands disappear from your server. Its data and settings are kept, so turning it on again carries on where it left off.

## Change a plugin's settings

See a plugin's settings:

```text
/plugins config plugin:giveaways
```

```json
{
  "default_minutes": 60,
  "excluded_role": null
}
```

Change one:

```text
/plugins config plugin:giveaways setting:default_minutes value:90
```

- Type numbers, and `true` or `false`, as they are.
- A channel, role or member is given by its ID. To copy an ID, turn on **Developer Mode** in Discord's **Advanced** settings, then right-click the channel, role or member and choose **Copy ID**.
- teabot checks the value, and says what is wrong if it does not fit.

Each plugin's page lists its settings: [Announcements](plugins/announcements.md) and [Giveaways](plugins/giveaways.md).

**Next:** [Who can use what](permissions.md).
