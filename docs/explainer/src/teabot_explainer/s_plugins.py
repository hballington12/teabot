"""Chapter III: what a plugin is, how it is made, where it lives, who approves it."""

import manimgx as m

from teabot_explainer.common import chapter_divider, new_slide, show_title
from teabot_explainer.theme import (
    BAD,
    BUTTER,
    CLAY,
    GOOD,
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
    card,
    chip,
    code_block,
    connect,
    cross,
    mono,
    serif,
    text,
    tick,
)

CH = "III · Plugins"

PLUGIN_CODE = """from teabot.sdk import ActionSpec, LongText, Manifest, Registrar, Risk

class PostInput(BaseModel):
    channel: ChannelRef
    title: str
    body: LongText

class Announcements:
    manifest = Manifest(id="announcements", version="0.1.0")

    def setup(self, r: Registrar) -> None:
        r.action(ActionSpec(
            name="announcements.post",
            summary="Post an announcement embed",
            input=PostInput, output=PostOutput,
            default_permissions=Permissions(manage_messages=True),
            risk=Risk.WRITE, run=post,
        ))

plugin = Announcements()"""


def chapter(s: m.Scene) -> None:
    """Run every slide of the chapter."""
    chapter_divider(s, 2, "Every feature is a plugin, including yours")
    anatomy_slide(s)
    three_doors_slide(s)
    authoring_slide(s)
    sources_slide(s)
    lifecycle_slide(s)
    limits_slide(s)


def anatomy_slide(s: m.Scene) -> None:
    """A plugin's code and the things it may declare."""
    new_slide(
        s,
        "What a plugin is",
        notes="A Python package with a teabot.plugins entry point. It imports only "
        "teabot.sdk, which is semantically versioned. Additions to the protocol arrive as "
        "fields with defaults, so old plugins keep working.",
    )
    show_title(s, "A plugin is a Python package", CH)
    listing = code_block(PLUGIN_CODE, size=15)
    listing.scale_to_fit_width(8.6).move_to([-2.6, -0.45, 0])
    s.play(m.FadeIn(listing, shift=m.UP * 0.15), run_time=0.8)
    head = serif("It can declare", 26, bold=True).move_to([4.75, 2.2, 0])
    declares = [
        ("actions", SAGE),
        ("buttons, selects, modals", SAGE),
        ("event hooks: join, leave, message", SAGE),
        ("scheduled jobs", SAGE),
        ("a config model per server", SKY),
        ("its own tables and migrations", SKY),
    ]
    chips = m.VGroup(*[chip(t, tone, 18) for t, tone in declares])
    for c in chips:
        c[0].stretch_to_fit_width(3.9)
    chips.arrange(m.DOWN, buff=0.16).next_to(head, m.DOWN, buff=0.3)
    later = text(
        "added when a plugin needs them:\n"
        "autocomplete, context menus, voice,\n"
        "MCP resources, HTTP routes, dependencies",
        16,
        MUTED,
    )
    later.next_to(chips, m.DOWN, buff=0.3)
    s.play(m.FadeIn(head), m.LaggedStart(*[m.FadeIn(c, shift=m.LEFT * 0.1) for c in chips], lag_ratio=0.12))
    s.play(m.FadeIn(later))


def three_doors_slide(s: m.Scene) -> None:
    """One ActionSpec becomes a slash command, an MCP tool and a service route."""
    new_slide(
        s,
        "One action, three doors",
        notes="One schema builder turns the Pydantic input model into both Discord's "
        "command JSON and the MCP tool schema, so they cannot drift apart. A LongText field "
        "opens a modal in Discord.",
    )
    show_title(s, "One action, three front doors", CH)
    spec_lines = m.VGroup(
        mono('name   "announcements.post"', 17),
        mono("input  PostInput", 17),
        mono("risk   WRITE", 17),
        mono("needs  Manage Messages", 17),
    ).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.18)
    spec_box = box(spec_lines.width + 0.7, spec_lines.height + 1.1, BUTTER)
    spec_head = serif("ActionSpec", 26, bold=True).next_to(spec_box.get_top(), m.DOWN, buff=0.2)
    spec_lines.next_to(spec_head, m.DOWN, buff=0.22)
    spec = m.VGroup(spec_box, spec_head, spec_lines).move_to([-4.3, -0.2, 0])
    builder = chip("one schema builder", STONE, 18).move_to([-0.95, -0.2, 0])
    doors = (
        m.VGroup(
            card(
                "Slash command",
                "/announcements post  channel:#events  title:…\nthe LongText body opens a modal",
                6.0,
                1.3,
                CLAY,
                22,
                16,
            ),
            card("MCP tool", "announcements_post\nannotations from the risk level", 6.0, 1.3, LAVENDER, 22, 16),
            card("Service API", "POST /api/v1/actions/announcements.post", 6.0, 1.3, SKY, 22, 16),
        )
        .arrange(m.DOWN, buff=0.3)
        .move_to([3.75, -0.2, 0])
    )
    s.play(m.FadeIn(spec, shift=m.RIGHT * 0.2))
    s.play(m.GrowArrow(connect(spec, builder)), m.FadeIn(builder))
    fan = m.VGroup(*[arrow(builder.get_right(), d.get_left()) for d in doors])
    s.play(
        m.LaggedStart(*[m.GrowArrow(a) for a in fan], lag_ratio=0.15),
        m.LaggedStart(*[m.FadeIn(d) for d in doors], lag_ratio=0.15),
    )
    note = text("An action can narrow itself to fewer doors with surfaces=.", 19, MUTED).move_to([0, -3.1, 0])
    s.play(m.FadeIn(note))


def authoring_slide(s: m.Scene) -> None:
    """The four steps from nothing to a plugin enabled in a server."""
    new_slide(
        s,
        "Making a plugin",
        notes="This is the path a self-hoster follows, from docs/plugin-authoring.md. "
        "Publishing to PyPI or git so other operators can install it is the author's choice.",
    )
    show_title(s, "Making a plugin", CH)
    steps = [
        ("1  Scaffold", "uv run teabot\nnew-plugin raffles", SAGE),
        (
            "2  Write and test",
            "actions against teabot.sdk,\ntests with teabot.testing\nagainst real Postgres",
            SKY,
        ),
        (
            "3  Restart",
            "the loader finds it, creates\nplugin_raffles and its role,\nruns the migrations",
            BUTTER,
        ),
        ("4  Enable", "/plugins enable raffles\nin a server", CLAY),
    ]
    cards = m.VGroup(*[card(t, b, 3.05, 1.95, tone, 23, 17) for t, b, tone in steps])
    cards.arrange(m.RIGHT, buff=0.32).move_to([0, 1.1, 0])
    links = m.VGroup(*[connect(cards[i], cards[i + 1]) for i in range(3)])
    for i, c in enumerate(cards):
        s.play(m.FadeIn(c, shift=m.UP * 0.15), *([m.GrowArrow(links[i - 1])] if i else []), run_time=0.5)
    tree = code_block(
        "plugins/raffles/\n"
        "    pyproject.toml        # entry point, pins teabot\n"
        "    README.md             # incl. External connections\n"
        "    src/teabot_raffles/\n"
        "    migrations/0001_init.sql\n"
        "    tests/",
        size=16,
        language="text",
    ).move_to([-2.4, -1.85, 0])
    quiet = (
        m.VGroup(
            serif("Nothing here contacts", 26, bold=True),
            serif("the teabot maintainers.", 26, bold=True),
        )
        .arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.1)
        .move_to([4.2, -1.85, 0])
    )
    s.play(m.FadeIn(tree, shift=m.UP * 0.1))
    s.play(m.FadeIn(quiet))


def sources_slide(s: m.Scene) -> None:
    """Where plugins come from, the lockfile, and who reviews what."""
    new_slide(
        s,
        "Where plugins live, who approves",
        notes="This is the RuneLite Plugin Hub model: a plugin is a repository and a "
        "pinned commit, and the instance's uv.lock plays the part of the signed manifest.",
    )
    show_title(s, "Where plugins live", CH)
    sources = (
        m.VGroup(
            card("In your instance repo", "plugins/raffles/", 3.5, 1.05, SAGE, 20, 16),
            card("A pinned git dependency", "git+<repo>@<commit>", 3.5, 1.05, SAGE, 20, 16),
            card("A release on PyPI", "teabot-giveaways==1.2.0", 3.5, 1.05, SAGE, 20, 16),
        )
        .arrange(m.DOWN, buff=0.25)
        .move_to([-5.2, 0.55, 0])
    )
    lock = card("uv.lock", "hashes of every\nplugin it runs", 2.2, 1.5, STONE, 24, 16).move_to([-1.55, 0.55, 0])
    s.play(m.LaggedStart(*[m.FadeIn(x, shift=m.RIGHT * 0.1) for x in sources], lag_ratio=0.15))
    feeds = m.VGroup(*[arrow(x.get_right(), lock.get_left()) for x in sources])
    s.play(m.LaggedStart(*[m.GrowArrow(f) for f in feeds], lag_ratio=0.1), m.FadeIn(lock))
    ladder = (
        m.VGroup(
            card(
                "Self-hosted",
                "the operator reviews the diff of every\npin bump: their review is the boundary",
                4.9,
                1.2,
                SKY,
                22,
                16,
            ),
            card(
                "Hosted service",
                "the maintainers review every plugin\nin its catalogue",
                4.9,
                1.2,
                LAVENDER,
                22,
                16,
            ),
            card(
                "Later: a plugin hub",
                "a catalogue of reviewed pins,\nreserving plugin ids across listings",
                4.9,
                1.2,
                None,
                22,
                16,
            ),
        )
        .arrange(m.DOWN, buff=0.22)
        .move_to([4.0, 0.55, 0])
    )
    s.play(m.LaggedStart(*[m.FadeIn(x, shift=m.LEFT * 0.1) for x in ladder], lag_ratio=0.2))
    checks = [
        "external connections declared",
        "async I/O only",
        "migrations keep the last release working",
        "jobs safe to run twice",
    ]
    row = m.VGroup(*[chip(c, BUTTER, 16) for c in checks]).arrange(m.RIGHT, buff=0.18)
    cap = text("the review checklist in every plugin pull request", 17, MUTED)
    group = m.VGroup(cap, row).arrange(m.DOWN, buff=0.18).move_to([0, -2.85, 0])
    s.play(m.FadeIn(group, lag_ratio=0.1))


def _lifecycle_row(step: str, who: str, effect: str, tone, kept: bool) -> m.VGroup:
    """One row of the lifecycle table."""
    a = chip(step, tone, 19)
    a[0].stretch_to_fit_width(2.6)
    b = text(who, 18)
    c = text(effect, 18)
    mark = tick(GOOD, 0.14) if kept else cross(BAD, 0.12)
    d = m.VGroup(mark, text("data kept" if kept else "data deleted", 18, GOOD if kept else BAD, bold=not kept))
    d.arrange(m.RIGHT, buff=0.18)
    a.move_to([-5.15, 0, 0])
    b.move_to([-3.6, 0, 0], aligned_edge=m.LEFT)
    c.move_to([-0.4, 0, 0], aligned_edge=m.LEFT)
    d.move_to([4.6, 0, 0], aligned_edge=m.LEFT)
    return m.VGroup(a, b, c, d)


def lifecycle_slide(s: m.Scene) -> None:
    """Six lifecycle steps, who takes each, and that only purge deletes data."""
    new_slide(
        s,
        "Plugin lifecycle",
        notes="Install, upgrade, uninstall and block change files and take effect at "
        "restart. Enable and disable are per server and immediate. Purge is the only step "
        "that deletes, and it refuses while any process has the plugin loaded.",
    )
    show_title(s, "A plugin's lifecycle", CH)
    rows_spec = [
        ("install, upgrade", "operator", "schema and role created, migrations run", SAGE, True),
        ("enable", "server admin", "commands appear in that server", SKY, True),
        ("disable", "server admin", "commands leave that server, jobs pause", SKY, True),
        ("uninstall", "operator", "commands leave everywhere", STONE, True),
        ("block", "operator", "TEABOT_DISABLED_PLUGINS, restart", STONE, True),
        ("purge", "operator CLI", "DROP SCHEMA plugin_x CASCADE", ROSE, False),
    ]
    rows = m.VGroup(*[_lifecycle_row(*r) for r in rows_spec]).arrange(m.DOWN, buff=0.3)
    rows.move_to([0, 0.15, 0])
    for r in rows:
        r[1].align_to(rows[0][1], m.LEFT)
        r[2].align_to(rows[0][2], m.LEFT)
        r[3].align_to(rows[0][3], m.LEFT)
    s.play(m.LaggedStart(*[m.FadeIn(r, shift=m.UP * 0.1) for r in rows], lag_ratio=0.15), run_time=1.8)
    s.play(m.Circumscribe(rows[5], color=ROSE.edge, buff=0.1))
    note = text(
        "A plugin that fails to import, set up or migrate is marked failed. Everything else starts.",
        19,
        MUTED,
    )
    note.move_to([0, -3.2, 0])
    s.play(m.FadeIn(note))


def limits_slide(s: m.Scene) -> None:
    """What a plugin can do, what the core stops it doing, and why review still matters."""
    new_slide(
        s,
        "What plugins can and cannot do",
        notes="The plugin protocol, the permission checks and the audit trail are the "
        "safety net. Postgres roles catch mistakes, they do not replace review.",
    )
    show_title(s, "What a plugin can and cannot do", CH)
    can = [
        "post, edit and react in its server",
        "manage roles, channels and overwrites",
        "listen to joins, leaves and messages",
        "schedule jobs that survive restarts",
        "keep its own tables and config",
    ]
    cannot = [
        "reach another server: its context holds one",
        "read core tables or other plugins' schemas",
        "skip the permission check or the audit log",
        "contact hosts it has not declared for review",
        "run on the hosted service unreviewed",
    ]
    cols = []
    for title, items, tone, ok in (("Can", can, SAGE, True), ("Cannot", cannot, ROSE, False)):
        rect = box(6.25, 4.0, tone)
        head = serif(title, 32, bold=True)
        lines = m.VGroup()
        for it in items:
            mark = tick(GOOD, 0.12) if ok else cross(BAD, 0.1)
            lines.add(m.VGroup(mark, text(it, 19)).arrange(m.RIGHT, buff=0.22))
        lines.arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.26)
        inner = m.VGroup(head, lines).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.3).move_to(rect)
        cols.append(m.VGroup(rect, inner))
    pair = m.VGroup(*cols).arrange(m.RIGHT, buff=0.4).move_to([0, 0.05, 0])
    s.play(m.FadeIn(pair[0], shift=m.UP * 0.15))
    s.play(m.FadeIn(pair[1], shift=m.UP * 0.15))
    note = text(
        "There is no sandbox: plugins run inside the bot's process, so code review is the boundary.",
        20,
    ).move_to([0, -2.85, 0])
    s.play(m.Write(note), run_time=1.2)
