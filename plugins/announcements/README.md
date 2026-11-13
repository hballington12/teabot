# teapot-announcements

A first-party plugin: post an announcement to a channel as an embed.

- `/announcements post`: a channel, a title, a body (typed in a modal, so it can span lines) and a colour. Needs Manage Messages by default. The reply links to the post.
- Also available as the MCP tool `announcements_post` and the service action `announcements.post`.
- Config: none yet.
- External connections: none (D12).
- Tests: `plugins/announcements/tests/`, through `teapot.testing`.
