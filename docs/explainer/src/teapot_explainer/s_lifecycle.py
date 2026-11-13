"""Chapter IV: one example session, from adding the bot to a destructive request."""

import manimgx as m

from teapot_explainer.common import chapter_divider, new_slide, show_title
from teapot_explainer.theme import (
    BUTTER,
    CARD,
    CLAY,
    FAINT,
    GOOD,
    INK,
    LAVENDER,
    MUTED,
    ROSE,
    SAGE,
    SKY,
)
from teapot_explainer.widgets import (
    box,
    bubble,
    bullets,
    card,
    chip,
    discord_message,
    embed,
    mono,
    serif,
    terminal,
    text,
    tool_call,
)

CH = "IV · A day in the life"
STAFF = "aria"  # a fictional staff member
BOT = "teapot"


def chapter(s: m.Scene) -> None:
    """Run every slide of the chapter."""
    chapter_divider(s, 3, "One staff member, one server, one AI agent")
    invite_slide(s)
    enable_slide(s)
    connect_slide(s)
    ask_slide(s)
    destructive_slide(s)


def panel(channel: str, width: float, height: float) -> m.VGroup:
    """A Discord channel window: a light box with the channel name in a header."""
    bg = box(width, height, None, radius=0.14)
    name = text(f"# {channel}", 19, MUTED, bold=True)
    name.next_to(bg.get_corner(m.UL), m.DR, buff=0.18)
    line = m.Line(bg.get_left(), bg.get_right(), color=FAINT, stroke_width=1.5)
    line.set_y(name.get_bottom()[1] - 0.14)
    return m.VGroup(bg, name, line)


def _place(items: m.VGroup, under: m.Mobject, left: m.Mobject, buff: float = 0.25) -> m.VGroup:
    """Stack items downwards under a header, aligned to a panel's left edge."""
    items.arrange(m.DOWN, aligned_edge=m.LEFT, buff=buff)
    items.next_to(under, m.DOWN, buff=0.3).align_to(left, m.LEFT).shift(m.RIGHT * 0.3)
    return items


def _role_row(name: str, colour: str, width: float = 4.2) -> m.VGroup:
    """One role in a server's role list."""
    dot = m.Dot(radius=0.09, color=colour)
    label = text(name, 20)
    row = m.VGroup(dot, label).arrange(m.RIGHT, buff=0.2)
    bg = box(width, 0.5, None, radius=0.08, stroke=1)
    row.move_to(bg).align_to(bg, m.LEFT).shift(m.RIGHT * 0.25)
    return m.VGroup(bg, row)


def invite_slide(s: m.Scene) -> None:
    """The invite link, and the bot's role dragged below the senior roles."""
    new_slide(
        s,
        "Add the bot",
        notes="A server admin invites the bot with the bot and applications.commands "
        "scopes. Discord's role hierarchy stops the bot editing roles above its own, even "
        "with Administrator, so its role goes below the owner and senior staff.",
    )
    show_title(s, "1 · Add the bot to your server", CH)
    link = m.VGroup(
        text("invite link", 17, MUTED),
        mono("discord.com/oauth2/authorize?client_id=<bot id>", 17),
        mono("    &scope=bot+applications.commands", 17),
    ).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.12)
    link_box = box(link.width + 0.6, link.height + 0.45, CLAY)
    link.move_to(link_box)
    invite = m.VGroup(link_box, link).move_to([-3.5, 1.6, 0])
    s.play(m.FadeIn(invite, shift=m.DOWN * 0.15))
    after = (
        bullets(
            [
                "core.guilds records the server",
                "/plugins, /audit and /tokens appear at once",
                "no plugin is enabled until an admin says so",
            ],
            size=20,
            buff=0.28,
        )
        .next_to(invite, m.DOWN, buff=0.6)
        .align_to(invite, m.LEFT)
    )
    s.play(m.LaggedStart(*[m.FadeIn(a, shift=m.RIGHT * 0.1) for a in after], lag_ratio=0.2))
    head = serif("Server settings → Roles", 22, bold=True).move_to([4.2, 2.15, 0])
    names = [
        ("Owner", ROSE.edge),
        ("Senior staff", LAVENDER.edge),
        ("Staff", SKY.edge),
        ("Event captains", BUTTER.edge),
        ("teapot", SAGE.edge),
    ]
    rows = m.VGroup(*[_role_row(n, c) for n, c in names]).arrange(m.DOWN, buff=0.1)
    rows.next_to(head, m.DOWN, buff=0.25)
    bot_row = rows[4]
    bot_row[0].set_fill(SAGE.fill).set_stroke(SAGE.edge, 2)
    s.play(m.FadeIn(head), m.LaggedStart(*[m.FadeIn(r) for r in rows], lag_ratio=0.1))
    slot = rows[2].get_center()
    s.play(
        bot_row.animate.move_to(slot),
        rows[2].animate.shift(m.DOWN * 0.6),
        rows[3].animate.shift(m.DOWN * 0.6),
        run_time=1.0,
    )
    note = text("below the owner and senior staff:\nDiscord then stops it editing those roles", 17, MUTED)
    note.next_to(rows, m.DOWN, buff=0.35)
    s.play(m.FadeIn(note))


def enable_slide(s: m.Scene) -> None:
    """Enable a plugin, set the log channel and create a token, all in Discord."""
    new_slide(
        s,
        "Enable a plugin and make a token",
        notes="Enabling syncs that plugin's commands to this server only. The token is shown "
        "once in an ephemeral reply. Only its SHA-256 hash is stored.",
    )
    show_title(s, "2 · Enable a plugin, make a token", CH)
    win = panel("bot-commands", 9.6, 5.6).move_to([-1.6, -0.55, 0])
    s.play(m.FadeIn(win))
    msgs = m.VGroup(
        discord_message(STAFF, LAVENDER.edge, "/plugins enable announcements"),
        discord_message(BOT, SAGE.edge, "announcements is enabled here. Its commands are syncing.", tag="APP"),
        discord_message(STAFF, LAVENDER.edge, "/audit channel #teapot-log"),
        discord_message(STAFF, LAVENDER.edge, "/tokens create label:claude-code max_risk:write"),
    )
    _place(msgs, win[2], win[0], buff=0.3)
    for msg in msgs:
        s.play(m.FadeIn(msg, shift=m.UP * 0.1), run_time=0.5)
    secret = m.VGroup(
        text("Only you can see this", 15, MUTED),
        mono("teapot_7Kq2_9fJrXa…Xc3w", 20, CLAY.edge),
        text("expires in 30 days · it will not be shown again", 15, MUTED),
    ).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.1)
    sbox = box(secret.width + 0.5, secret.height + 0.35, CLAY, radius=0.1)
    secret.move_to(sbox)
    reply = m.VGroup(sbox, secret).next_to(msgs, m.DOWN, buff=0.25).align_to(msgs, m.LEFT).shift(m.RIGHT * 0.62)
    s.play(m.FadeIn(reply, shift=m.UP * 0.1))
    side = bullets(
        [
            "any member can make\ntokens for themselves",
            "a token never holds\nmore than its creator",
            "write by default:\ndestructive is opt-in",
        ],
        size=18,
        buff=0.3,
    ).move_to([5.2, -0.3, 0])
    s.play(m.FadeIn(side, lag_ratio=0.2))


def connect_slide(s: m.Scene) -> None:
    """Register the MCP server in Claude Code with the token."""
    new_slide(
        s,
        "Connect your agent",
        notes="One MCP entry per server the staff member works in, because a token is bound "
        "to one server. OAuth for claude.ai and the desktop app is a later addition.",
    )
    show_title(s, "3 · Connect your local AI agent", CH)
    term = terminal(
        [
            ("cmd", "claude mcp add --transport http tea \\"),
            ("out", "    https://teapot.example.org/mcp \\"),
            ("out", '    --header "Authorization: Bearer teapot_7Kq2_…"'),
            ("ok", "Added HTTP MCP server tea"),
            ("cmd", "claude"),
            ("out", "> /mcp"),
            ("ok", "  tea   ✔ connected · 5 tools"),
        ],
        width=8.6,
        size=19,
    ).move_to([-2.0, 0.75, 0])
    s.play(m.FadeIn(term[0]), m.FadeIn(term[1]))
    for line in term[2]:
        s.play(m.FadeIn(line, shift=m.RIGHT * 0.1), run_time=0.35)
    tools = m.VGroup(
        chip("admin_describe_guild", SAGE, 16, code=True),
        chip("admin_find_members", SAGE, 16, code=True),
        chip("admin_job_status", SAGE, 16, code=True),
        chip("announcements_post", BUTTER, 16, code=True),
        chip("announcements_schedule", BUTTER, 16, code=True),
    ).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.14)
    tools_head = serif("what the agent sees", 22, bold=True)
    col = m.VGroup(tools_head, tools).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.25).move_to([4.75, 0.75, 0])
    s.play(m.FadeIn(col, lag_ratio=0.1))
    notes = text(
        "One entry per server you work in. The list holds only plugins enabled in that server, up to the token's risk.",
        19,
        MUTED,
    ).move_to([0, -2.85, 0])
    s.play(m.FadeIn(notes))


def _chat(items: m.VGroup) -> m.VGroup:
    """Lay chat items out down the left column: user bubbles right, the rest left."""
    items.arrange(m.DOWN, buff=0.2)
    left = -6.75
    right = -0.35
    for it in items:
        if getattr(it, "is_user", False):
            it.set_x(right - it.width / 2)
        else:
            it.set_x(left + it.width / 2)
    return items


def _user(s: str) -> m.VGroup:
    b = bubble(s, CLAY, 18, 5.6)
    b.is_user = True  # ty: ignore[unresolved-attribute]
    return b


def ask_slide(s: m.Scene) -> None:
    """Ask the agent for an announcement and watch it land, with the audit post."""
    new_slide(
        s,
        "Ask it",
        notes="The agent looks up the channel id with a READ action, then calls the WRITE "
        "action. Both go through the call path. Only the post reaches the log channel, "
        "since reads are recorded but never posted.",
    )
    show_title(s, "4 · Ask it to do something", CH)
    chat = _chat(
        m.VGroup(
            _user("Post an announcement in #events: bingo starts\nSaturday 18:00 UTC, sign-ups in #bingo."),
            tool_call("admin_describe_guild", "{}  →  #events is 1180…"),
            tool_call("announcements_post", '{channel: "1180…", title: "Bingo this Saturday", body: …}'),
            bubble("Posted in #events.", LAVENDER, 18),
        )
    ).move_to([-3.55, -0.2, 0], coor_mask=[0, 1, 0])
    events = panel("events", 6.1, 2.75).move_to([3.6, 0.95, 0])
    post = embed("Bingo this Saturday", "Starts 18:00 UTC (shown in your time).\nSign up in #bingo.", SAGE.edge, 5.0)
    msg = discord_message(BOT, SAGE.edge, post, tag="APP")
    _place(m.VGroup(msg), events[2], events[0])
    log = panel("teapot-log", 6.1, 1.55).move_to([3.6, -1.75, 0])
    entry = discord_message(BOT, SAGE.edge, f"@{STAFF} via mcp · announcements.post · ok", tag="APP")
    _place(m.VGroup(entry), log[2], log[0])
    s.play(m.FadeIn(events), m.FadeIn(log))
    s.play(m.FadeIn(chat[0], shift=m.UP * 0.1))
    s.play(m.FadeIn(chat[1], shift=m.UP * 0.1))
    s.play(m.FadeIn(chat[2], shift=m.UP * 0.1))
    s.play(m.FadeIn(msg, shift=m.UP * 0.15))
    s.play(m.FadeIn(entry, shift=m.UP * 0.1), m.FadeIn(chat[3], shift=m.UP * 0.1))
    s.play(m.Indicate(entry, color=SAGE.edge, scale_factor=1.03))


def _progress(total: int, width: float = 4.6) -> tuple[m.ValueTracker, m.VGroup]:
    """A progress bar and counter driven by a tracker."""
    t = m.ValueTracker(0)
    track = m.RoundedRectangle(
        corner_radius=0.08,
        width=width,
        height=0.26,
        fill_color=CARD,
        fill_opacity=1,
        stroke_color=FAINT,
        stroke_width=1.5,
    )

    def fill() -> m.Mobject:
        w = max(width * t.get_value() / total, 0.01)
        bar = m.RoundedRectangle(
            corner_radius=0.08, width=w, height=0.26, fill_color=SAGE.edge, fill_opacity=1, stroke_width=0
        )
        return bar.align_to(track, m.LEFT).set_y(track.get_y())

    def count() -> m.Mobject:
        return mono(f"{round(t.get_value())}/{total} members", 16, INK).next_to(track, m.RIGHT, buff=0.2)

    bar = m.always_redraw(fill)
    label = m.always_redraw(count)
    return t, m.VGroup(track, bar, label)


def destructive_slide(s: m.Scene) -> None:
    """A bulk role removal: a plan first, the human agrees, then a queued apply."""
    new_slide(
        s,
        "Something destructive",
        notes="roles_bulk_remove stands in for a future roles plugin. Without confirm, the "
        "action returns a plan and a confirm value. The agent must show the plan and get "
        "agreement. The apply is refused if anything changed since the plan.",
    )
    show_title(s, "5 · Something destructive", CH)
    plan = m.VGroup(
        mono("plan    remove Team Red from 42", 15),
        mono("skip    3 above the bot's role", 15),
        mono("confirm Qx81tW…", 15),
    ).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.08)
    plan_box = box(plan.width + 0.4, plan.height + 0.3, ROSE, radius=0.1)
    plan.move_to(plan_box)
    tracker, bar = _progress(42, 3.0)
    call = tool_call("roles_bulk_remove", '{role: "Team Red", confirm: "Qx81tW…"}  →  job 7')
    job = m.VGroup(call, bar).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.18)
    chat = _chat(
        m.VGroup(
            _user("The event is over. Remove the\nTeam Red role from everyone."),
            tool_call("roles_bulk_remove", '{role: "Team Red"}'),
            m.VGroup(plan_box, plan),
            bubble("This removes Team Red from 42 members\nand skips 3. Shall I apply it?", LAVENDER, 18),
            _user("Yes, go ahead."),
            job,
        )
    )
    _chat(chat).move_to([-3.55, -0.62, 0], coor_mask=[0, 1, 0])
    for item in chat[:-1]:
        s.play(m.FadeIn(item, shift=m.UP * 0.1), run_time=0.45)
    s.play(m.FadeIn(call), m.FadeIn(bar))
    checks = (
        m.VGroup(
            card(
                "The plan is an audit row",
                "action, input, a hash of the diff,\nand a random confirm value",
                5.6,
                1.15,
                ROSE,
                21,
                16,
            ),
            card(
                "The apply checks again",
                "same member, same input, under 15 minutes\nold, and the diff hash unchanged",
                5.6,
                1.15,
                BUTTER,
                21,
                16,
            ),
            card(
                "It runs as a queued job",
                "one apply per server at a time,\nwith progress, linked to its plan",
                5.6,
                1.15,
                SAGE,
                21,
                16,
            ),
        )
        .arrange(m.DOWN, buff=0.22)
        .move_to([3.85, -0.2, 0])
    )
    s.play(m.LaggedStart(*[m.FadeIn(c, shift=m.LEFT * 0.1) for c in checks], lag_ratio=0.2))
    s.play(tracker.animate.set_value(42), run_time=2.5, rate_func=m.linear)
    done = text("✔ done", 18, GOOD, bold=True).next_to(bar, m.RIGHT, buff=0.25)
    s.play(m.FadeIn(done))
