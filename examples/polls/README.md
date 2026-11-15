# teabot-polls

- The plugin the documentation's tutorial builds: https://teabot-dev.github.io/teabot/plugins/tutorial/
- `/polls start` posts a poll with two to four options; `/polls vote` votes, and voting again changes the vote; `/polls list` shows the running polls; `/polls delete` deletes one, after a plan.
- When time is up, a job closes the poll and posts the results.
- The tutorial includes this code through the `# --8<-- [start:...]` markers. Keep them when you change it.
- It does not ship with teabot. Its tests run with teabot's own.
- External connections: none.
