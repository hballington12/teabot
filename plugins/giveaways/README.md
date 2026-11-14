# teabot-giveaways

- `/giveaways start`: a moderator starts a giveaway in a channel, with a prize, how many winners, and how long it runs. The bot announces it there.
- `/giveaways enter`: a member enters a running giveaway.
- `/giveaways list`: the server's running giveaways, shown to the channel.
- `/giveaways cancel`: cancels a running giveaway and its draw, after showing what it will cancel.
- When time is up, a job draws the winners at random, marks them, and announces them in the channel, mentioning only the winners.
- Config: `default_minutes`, how long a giveaway runs when `start` is not told; `excluded_role`, a role whose members may not enter.
- It is the worked example of `docs/tutorial.md`.
- External connections: none (D12).
