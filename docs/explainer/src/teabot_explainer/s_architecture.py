"""Chapter I: the core, its front doors, who owns what, entry points, the edge and MCP."""

import manimgx as m

from teabot_explainer.common import chapter_divider, new_slide, show_title
from teabot_explainer.theme import (
    BAD,
    BUTTER,
    CLAY,
    GOOD,
    INK,
    LAVENDER,
    MUTED,
    ROSE,
    SAGE,
    SKY,
    STONE,
)
from teabot_explainer.widgets import (
    arrow,
    box,
    bullets,
    card,
    chip,
    code_block,
    connect,
    cross,
    mono,
    serif,
    terminal,
    text,
    tick,
)

CH = "I · Architecture"


def chapter(s: m.Scene) -> None:
    """Run every slide of the chapter."""
    chapter_divider(s, 0, "How the pieces fit inside one instance")
    overview_slide(s)
    call_path_slide(s)
    owners_slide(s)
    entry_points_slide(s)
    edge_slide(s)
    mcp_slide(s)


def _overview_parts() -> dict[str, m.VGroup]:
    """Build the boxes of the overview diagram at their places."""
    rows = [1.5, 0.0, -1.5]
    callers = m.VGroup(
        card("Members & staff", "in the Discord app", 2.35, 1.05, CLAY, 20, 15),
        card("Your AI agent", "Claude Code, over MCP", 2.35, 1.05, LAVENDER, 20, 15),
        card("Other programs", "an event backend", 2.35, 1.05, BUTTER, 20, 15),
    )
    doors = m.VGroup(
        card("Slash commands", "/announcements post", 2.3, 1.05, None, 20, 14),
        card("MCP", "/mcp", 2.3, 1.05, None, 20, 15),
        card("Service API", "/api/v1/actions/…", 2.3, 1.05, None, 20, 14),
    )
    for group, x in ((callers, -5.9), (doors, -2.25)):
        for item, y in zip(group, rows, strict=True):
            item.move_to([x, y, 0])
    caddy_box = box(0.5, 2.6, STONE).move_to([-4.1, -0.75, 0])
    caddy_label = text("Caddy · TLS", 16).rotate(m.PI / 2).move_to(caddy_box)
    core_box = box(3.1, 4.1, SAGE).move_to([1.05, 0.0, 0])
    core_head = serif("teabot core", 26, bold=True).next_to(core_box.get_top(), m.DOWN, 0.22)
    parts = ["action registry", "permission check", "audit log", "plan, then apply", "work queue"]
    inner = m.VGroup(*[chip(p, STONE, 17) for p in parts]).arrange(m.DOWN, buff=0.14)
    for c in inner:
        c[0].stretch_to_fit_width(2.5)
    inner.next_to(core_head, m.DOWN, buff=0.25)
    names = ["announcements", "giveaways", "moderation", "your own plugin"]
    plugins = m.VGroup(*[card(n, None, 2.5, 0.72, BUTTER if i < 3 else None, 19) for i, n in enumerate(names)])
    plugins.arrange(m.DOWN, buff=0.28).move_to([5.15, 0.0, 0])
    db = card("Postgres", "config · plugin tables · tokens · jobs · audit", 6.9, 0.85, SKY, 22, 16)
    db.move_to([2.95, -3.05, 0])
    return {
        "callers": callers,
        "doors": doors,
        "caddy": m.VGroup(caddy_box, caddy_label),
        "core": m.VGroup(core_box, core_head, inner),
        "plugins": plugins,
        "db": db,
    }


def overview_slide(s: m.Scene) -> None:
    """Callers, front doors, the core, plugins and Postgres in one picture."""
    new_slide(
        s,
        "The big picture",
        notes="One Python process runs discord.py, uvicorn for MCP and the API, and the "
        "queue workers in one asyncio loop. Postgres sits beside it. Caddy is in front of "
        "the HTTP doors only, since Discord traffic is an outbound gateway connection.",
    )
    show_title(s, "The big picture", CH)
    p = _overview_parts()
    callers, doors, core, plugins = p["callers"], p["doors"], p["core"], p["plugins"]
    s.play(m.LaggedStart(*[m.FadeIn(c, shift=m.RIGHT * 0.2) for c in callers], lag_ratio=0.2))
    gw = text("gateway", 14, MUTED).next_to(m.VGroup(callers[0], doors[0]), m.UP, buff=-0.38).set_x(-4.1)
    in_arrows = m.VGroup(
        connect(callers[0], doors[0]),
        arrow(callers[1].get_right(), p["caddy"].get_left() + m.UP * 0.75),
        arrow(callers[2].get_right(), p["caddy"].get_left() + m.DOWN * 0.75),
        arrow(p["caddy"].get_right() + m.UP * 0.75, doors[1].get_left()),
        arrow(p["caddy"].get_right() + m.DOWN * 0.75, doors[2].get_left()),
    )
    s.play(m.FadeIn(p["caddy"]), m.FadeIn(doors, lag_ratio=0.2), m.FadeIn(gw))
    s.play(m.LaggedStart(*[m.GrowArrow(a) for a in in_arrows], lag_ratio=0.1))
    core_in = m.VGroup(*[arrow(d.get_right(), [core[0].get_left()[0], d.get_y(), 0]) for d in doors])
    s.play(
        m.FadeIn(core[0]),
        m.Write(core[1]),
        m.GrowArrow(core_in[0]),
        m.GrowArrow(core_in[1]),
        m.GrowArrow(core_in[2]),
    )
    s.play(m.LaggedStart(*[m.FadeIn(c, shift=m.UP * 0.1) for c in core[2]], lag_ratio=0.15))
    out = m.VGroup(*[arrow([core[0].get_right()[0], pl.get_y(), 0], pl.get_left()) for pl in plugins])
    s.play(
        m.LaggedStart(*[m.GrowArrow(a) for a in out], lag_ratio=0.1),
        m.LaggedStart(*[m.FadeIn(pl) for pl in plugins], lag_ratio=0.1),
    )
    down = m.VGroup(
        arrow(core[0].get_bottom(), [core[0].get_x(), p["db"].get_top()[1], 0]),
        arrow(plugins.get_bottom(), [plugins.get_x(), p["db"].get_top()[1], 0]),
    )
    note = text("one asyncio process:\ndiscord.py · uvicorn · queue workers", 17, MUTED)
    note.move_to([-4.6, -3.05, 0])
    s.play(m.FadeIn(p["db"], shift=m.UP * 0.2), m.GrowArrow(down[0]), m.GrowArrow(down[1]), m.FadeIn(note))
    s.play(m.Circumscribe(core[2][0], color=SAGE.edge, buff=0.06))


def call_path_slide(s: m.Scene) -> None:
    """The eight steps every call takes, with a call travelling through them."""
    new_slide(
        s,
        "One call path",
        notes="Every front door builds the same context and calls registry.invoke. "
        "Slash calls take the server from the interaction, token calls from the token.",
    )
    show_title(s, "Every call takes one path", CH)
    steps = [
        ("1", "Resolve the server"),
        ("2", "Plugin enabled\nhere?"),
        ("3", "Token risk and\nallow-list"),
        ("4", "Validate the input"),
        ("5", "Live permission\ncheck"),
        ("6", "Audit row\n'started'"),
        ("7", "Run it, or plan\nif destructive"),
        ("8", "Record outcome,\npost to log channel"),
    ]
    xs = [-4.875, -1.625, 1.625, 4.875]
    chips = m.VGroup()
    for i, (n, label) in enumerate(steps):
        tone = SAGE if i < 4 else SKY
        rect = box(2.7, 1.25, tone)
        num = serif(n, 30, tone.edge, bold=True)
        body = text(label, 18)
        m.VGroup(num, body).arrange(m.RIGHT, buff=0.22).move_to(rect)
        x = xs[i] if i < 4 else xs[7 - i]
        y = 1.0 if i < 4 else -0.9
        chips.add(m.VGroup(rect, num, body).move_to([x, y, 0]))
    links = m.VGroup(
        *[connect(chips[i], chips[i + 1]) for i in range(3)],
        arrow(chips[3].get_bottom(), chips[4].get_top()),
        *[arrow(chips[i].get_left(), chips[i + 1].get_right()) for i in range(4, 7)],
    )
    s.play(m.LaggedStart(*[m.FadeIn(c, shift=m.UP * 0.1) for c in chips], lag_ratio=0.1))
    s.play(m.LaggedStart(*[m.GrowArrow(a) for a in links], lag_ratio=0.08))
    call = m.Dot(radius=0.13, color=INK).move_to(chips[0].get_top() + m.UP * 0.15)
    s.play(m.FadeIn(call))
    for c in chips:
        target = c.get_top() + m.UP * 0.15 if c.get_y() > 0 else c.get_bottom() + m.DOWN * 0.15
        s.play(call.animate.move_to(target), c[0].animate.set_stroke(INK, 3), run_time=0.35)
    done = text("Slash, MCP and the API share this path, and so does the core's own admin plugin.", 21)
    done.move_to([0, -2.55, 0])
    s.play(call.animate.set_color(GOOD), m.FadeIn(done, shift=m.UP * 0.1))
    s.next_section("A refused call", notes="A member without Manage Roles stops at step 5.")
    s.play(m.FadeOut(done), call.animate.set_color(INK).move_to(chips[0].get_top() + m.UP * 0.15))
    s.play(*[c[0].animate.set_stroke(c[0].get_stroke_color(), 2) for c in chips], run_time=0.3)
    for c in chips[:5]:
        target = c.get_top() + m.UP * 0.15 if c.get_y() > 0 else c.get_bottom() + m.DOWN * 0.15
        s.play(call.animate.move_to(target), run_time=0.3)
    stop = text("Missing Manage Roles: refused before anything runs.", 21, BAD)
    stop.move_to([0, -2.55, 0])
    s.play(
        call.animate.set_color(BAD),
        chips[4][0].animate.set_fill(ROSE.fill).set_stroke(ROSE.edge, 3),
        m.FadeIn(stop),
    )
    s.play(m.Wiggle(chips[4]))


def owners_slide(s: m.Scene) -> None:
    """The five roles and what each one controls."""
    new_slide(
        s,
        "Who owns what",
        notes="The operator is whoever runs an instance: the Tea clan for its own, a "
        "self-hoster for theirs, and the maintainers for the hosted service.",
    )
    show_title(s, "Who owns what", CH)
    roles = [
        (
            "Operator",
            "runs an instance: bot token,\ndatabase, deploys. Installs,\nupgrades, blocks, purges plugins",
            SAGE,
        ),
        ("Server admin", "enables, disables and\nconfigures installed plugins\nin their own server", SKY),
        ("Staff & members", "use the commands. Create\ntokens that act as themselves,\nnever as more", CLAY),
        (
            "Plugin author",
            "anyone. Writes a package\nagainst teabot.sdk, with no\napproval needed to self-host",
            BUTTER,
        ),
        (
            "teabot maintainers",
            "the framework, first-party\nplugins, the template, and the\nhosted service's catalogue",
            LAVENDER,
        ),
    ]
    cards = [card(t, b, 4.25, 2.25, tone, 27, 19) for t, b, tone in roles]
    top = m.VGroup(*cards[:3]).arrange(m.RIGHT, buff=0.3)
    bottom = m.VGroup(*cards[3:]).arrange(m.RIGHT, buff=0.3)
    grid = m.VGroup(top, bottom).arrange(m.DOWN, buff=0.35).shift(m.DOWN * 0.45)
    s.play(m.LaggedStart(*[m.FadeIn(c, shift=m.UP * 0.2) for c in cards], lag_ratio=0.15))
    s.play(m.Circumscribe(grid[0][0], color=SAGE.edge, buff=0.05))


def entry_points_slide(s: m.Scene) -> None:
    """The one CLI, what `teabot run` does at start, and the plugin entry point."""
    new_slide(
        s,
        "Entry points",
        notes="uv run teabot is the only executable. The CLI works on the database alone. "
        "Plugins are found through Python entry points, so nothing is registered by hand.",
    )
    show_title(s, "Entry points", CH)
    term = terminal(
        [
            ("cmd", "uv run teabot init"),
            ("note", "  # database roles, secrets, Discord app settings"),
            ("cmd", "uv run teabot run"),
            ("note", "  # start a bot process (systemd or Compose)"),
            ("cmd", "uv run teabot plugins list"),
            ("note", "  # what is loaded, read from pg_locks"),
            ("cmd", "uv run teabot new-plugin raffles"),
            ("cmd", "uv run teabot plugins purge devtools"),
        ],
        width=7.4,
        size=18,
    ).move_to([-2.9, 0.75, 0])
    toml = code_block(
        '[project.entry-points."teabot.plugins"]\nannouncements = "teabot_announcements:plugin"',
        size=17,
        language="toml",
    )
    toml.next_to(term, m.DOWN, buff=0.35).align_to(term, m.LEFT)
    cap = text("a plugin announces itself through its pyproject.toml", 16, MUTED)
    cap.next_to(toml, m.DOWN, buff=0.15).align_to(toml, m.LEFT)
    s.play(m.FadeIn(term[0]), m.FadeIn(term[1]))
    s.play(m.LaggedStart(*[m.FadeIn(line, shift=m.RIGHT * 0.1) for line in term[2]], lag_ratio=0.15))
    head = serif("teabot run, at start", 24, bold=True).move_to([4.6, 2.3, 0])
    flow = [
        "read teabot.env",
        "take shard locks",
        "migrate, under one\nadvisory lock",
        "load plugins",
        "gateway · uvicorn ·\nqueue workers",
    ]
    chips = m.VGroup(*[chip(f, SAGE if i < 4 else SKY, 17) for i, f in enumerate(flow)])
    for c in chips:
        c[0].stretch_to_fit_width(3.2)
    chips.arrange(m.DOWN, buff=0.28).next_to(head, m.DOWN, buff=0.3)
    links = m.VGroup(*[arrow(chips[i].get_bottom(), chips[i + 1].get_top(), buff=0.03) for i in range(4)])
    s.play(m.FadeIn(head))
    s.play(
        m.LaggedStart(*[m.FadeIn(c) for c in chips], lag_ratio=0.2),
        m.LaggedStart(*[m.GrowArrow(a) for a in links], lag_ratio=0.2),
    )
    s.play(m.FadeIn(toml, shift=m.UP * 0.1), m.FadeIn(cap))


def edge_slide(s: m.Scene) -> None:
    """Caddy terminates TLS and forwards only /mcp and /api to the bot on localhost."""
    new_slide(
        s,
        "Caddy at the edge",
        notes="HTTPS at the edge and plain HTTP only on localhost. /healthz lists the "
        "installed plugins, so it is never forwarded. Deploy scripts call it locally.",
    )
    show_title(s, "Caddy at the edge", CH)
    agent = card("AI agent, backend", "HTTPS + bearer token", 2.9, 1.25, LAVENDER, 22, 16).move_to([-5.4, 1.35, 0])
    caddy = card("Caddy", "teabot.example.org\nterminates TLS", 2.7, 1.25, STONE, 24, 16).move_to([-1.45, 1.35, 0])
    bot = card("teabot process", "127.0.0.1:8080", 2.9, 1.25, SAGE, 22, 16).move_to([2.6, 1.35, 0])
    discord = card("Discord", "outbound gateway", 2.3, 1.0, CLAY, 22, 15).move_to([5.75, -0.35, 0])
    pg = card("Postgres", "Unix socket only", 2.3, 1.0, SKY, 22, 15).move_to([2.6, -0.35, 0])
    s.play(m.FadeIn(agent), m.FadeIn(caddy), m.FadeIn(bot))
    s.play(m.GrowArrow(connect(agent, caddy)), m.GrowArrow(connect(caddy, bot)))
    routes = m.VGroup(
        m.VGroup(tick(GOOD), mono("/mcp", 18)),
        m.VGroup(tick(GOOD), mono("/api", 18)),
        m.VGroup(cross(BAD), mono("/healthz  localhost only", 18)),
    )
    for r in routes:
        r.arrange(m.RIGHT, buff=0.25)
    routes.arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.3).next_to(caddy, m.DOWN, buff=0.4).align_to(caddy, m.LEFT)
    s.play(m.LaggedStart(*[m.FadeIn(r, shift=m.RIGHT * 0.1) for r in routes], lag_ratio=0.3))
    s.play(
        m.FadeIn(pg),
        m.FadeIn(discord),
        m.GrowArrow(arrow(bot.get_bottom(), pg.get_top())),
        m.GrowArrow(arrow(bot.get_right(), discord.get_top())),
    )
    caddyfile = (
        code_block(
            "teabot.example.org {\n    handle /mcp* {\n        reverse_proxy 127.0.0.1:8080\n    }\n"
            "    handle /api/* {\n        reverse_proxy 127.0.0.1:8080\n    }\n"
            "    handle {\n        respond 404\n    }\n}",
            size=15,
            language="text",
        )
        .scale(0.86)
        .move_to([3.9, -2.45, 0])
    )
    note = text("One public HTTPS URL,\nso there is one path\nto secure and log.", 21, MUTED)
    note.move_to([-5.3, -1.3, 0])
    s.play(m.FadeIn(caddyfile, shift=m.UP * 0.1), m.FadeIn(note))


def _token_anatomy() -> m.VGroup:
    """The token string with braces naming its three parts."""
    parts = [
        mono("teabot_", 36),
        mono("7Kq2", 36, SKY.edge),
        mono("_", 36),
        mono("9fJrXa…Xc3w", 36, CLAY.edge),
    ]
    row = m.VGroup(*parts).arrange(m.RIGHT, buff=0.02).move_to([0, 1.95, 0])
    labels = [
        ("prefix: scanners spot leaks", parts[0]),
        ("token id: finds the row", parts[1]),
        ("secret: stored as SHA-256", parts[3]),
    ]
    braces = m.VGroup()
    for label, part in labels:
        b = m.Brace(part, m.DOWN, buff=0.08, color=MUTED)
        t = text(label, 17, MUTED).next_to(b, m.DOWN, buff=0.08)
        braces.add(m.VGroup(b, t))
    braces[1][1].shift(m.DOWN * 0.42)
    braces[0][1].shift(m.LEFT * 0.4)
    braces[2][1].shift(m.RIGHT * 0.3)
    return m.VGroup(row, braces)


def mcp_slide(s: m.Scene) -> None:
    """What a token is, what it may do, and how the tool list is filtered."""
    new_slide(
        s,
        "MCP and tokens",
        notes="An LLM acts for one staff member in one server. Every audit row names the "
        "human. Destructive tools always return a plan first, and the server instructions "
        "tell the agent to show it to its user before confirming.",
    )
    show_title(s, "MCP: an agent acting as you", CH)
    anatomy = _token_anatomy()
    s.play(m.Write(anatomy[0]), run_time=1.2)
    s.play(m.LaggedStart(*[m.FadeIn(b) for b in anatomy[1]], lag_ratio=0.2))
    props = bullets(
        [
            "Bound to one server: no tool takes a guild id",
            "Acts as its creator, with roles checked live",
            "A maximum risk: read < write < destructive",
            "An optional allow-list of action names",
            "Shown once, expires, can be revoked",
            "Member-written text comes back marked untrusted",
        ],
        size=19,
        buff=0.22,
    ).move_to([-3.3, -1.55, 0])
    s.play(m.LaggedStart(*[m.FadeIn(p, shift=m.RIGHT * 0.1) for p in props], lag_ratio=0.12))
    panel = box(6.2, 3.1).move_to([3.65, -1.55, 0])
    head = serif("tools/list for a write token", 21, bold=True).next_to(panel.get_top(), m.DOWN, 0.2)
    tools = [
        ("admin_describe_guild", "read", True),
        ("admin_find_members", "read", True),
        ("announcements_post", "write", True),
        ("roles_bulk_remove", "destructive", False),
    ]
    rows = m.VGroup()
    for name, risk, _ok in tools:
        n = mono(name, 17)
        r = chip(risk, SAGE if risk == "read" else BUTTER if risk == "write" else ROSE, 17, pad=0.08)
        rows.add(m.VGroup(n, r))
    for row in rows:
        row[1].move_to([panel.get_right()[0] - 1.0, 0, 0])
    rows.arrange(m.DOWN, buff=0.22).next_to(head, m.DOWN, buff=0.25)
    for row in rows:
        row[0].align_to(panel, m.LEFT).shift(m.RIGHT * 0.35)
        row[1].set_x(panel.get_right()[0] - 1.0)
    s.play(m.FadeIn(panel), m.FadeIn(head), m.LaggedStart(*[m.FadeIn(r) for r in rows], lag_ratio=0.15))
    strike = m.Line(rows[3].get_left(), rows[3].get_right(), color=BAD, stroke_width=3)
    s.play(m.Create(strike), rows[3].animate.set_opacity(0.45))
