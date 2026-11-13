"""Chapter II: instances, the licence, hosted against self-hosted, bot identity, data, scale."""

import manimgx as m

from teapot_explainer.common import chapter_divider, new_slide, show_title
from teapot_explainer.theme import (
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
from teapot_explainer.widgets import (
    arrow,
    avatar,
    box,
    bullets,
    card,
    chip,
    cross,
    mono,
    serif,
    text,
)

CH = "II · Hosting"


def chapter(s: m.Scene) -> None:
    """Run every slide of the chapter."""
    chapter_divider(s, 1, "Who runs a teapot, under which licence, and how it grows")
    instances_slide(s)
    licence_slide(s)
    hosted_slide(s)
    identity_slide(s)
    database_slide(s)
    scaling_slide(s)


def _instance(title: str, body: str, tone) -> m.VGroup:
    """An instance card with the four things every instance owns."""
    rect = box(4.0, 3.15, tone)
    head = serif(title, 25, bold=True)
    sub = text(body, 16)
    owned = ["its own Discord app and bot id", "its own bot token", "its own Postgres", "its own operator"]
    items = m.VGroup(*[chip(o, STONE, 15, pad=0.08) for o in owned])
    for c in items:
        c[0].stretch_to_fit_width(3.4)
    items.arrange(m.DOWN, buff=0.1)
    inner = m.VGroup(head, sub, items).arrange(m.DOWN, buff=0.16).move_to(rect)
    return m.VGroup(rect, inner)


def instances_slide(s: m.Scene) -> None:
    """One framework repository, many independent instances."""
    new_slide(
        s,
        "Framework and instances",
        notes="This repository is the framework. An instance is a small project made from "
        "the template: a pyproject listing its plugins, a uv.lock, an env file and deploy "
        "files. Separate applications keep rate limits and Discord reviews apart.",
    )
    show_title(s, "One framework, many instances", CH)
    fw = card(
        "teapot framework",
        "core · teapot.sdk · first-party plugins · instance template\npublished to PyPI as teapot and teapot-<plugin>",
        7.6,
        1.4,
        STONE,
        28,
        18,
    ).move_to([0, 1.75, 0])
    insts = (
        m.VGroup(
            _instance("Tea clan's instance", "a DigitalOcean droplet, Caddy, systemd", SAGE),
            _instance("Hosted teapot", "run by the maintainers for everyone", SKY),
            _instance("Your instance", "Docker Compose in minutes", BUTTER),
        )
        .arrange(m.RIGHT, buff=0.35)
        .move_to([0, -1.35, 0])
    )
    s.play(m.FadeIn(fw, shift=m.DOWN * 0.2))
    links = m.VGroup(*[arrow(fw.get_bottom(), i.get_top(), buff=0.1) for i in insts])
    s.play(m.LaggedStart(*[m.GrowArrow(a) for a in links], lag_ratio=0.15))
    s.play(m.LaggedStart(*[m.FadeIn(i, shift=m.UP * 0.2) for i in insts], lag_ratio=0.2))


def licence_slide(s: m.Scene) -> None:
    """Apache-2.0 as the leading choice, what it covers and when it must be settled."""
    new_slide(
        s,
        "Open-source licence",
        notes="Open decision 1. Apache-2.0 leads for its explicit patent grant. MIT or "
        "BSD-2-Clause also fit. Changing it later needs every contributor's agreement, so "
        "it is settled before the first outside contribution.",
    )
    show_title(s, "Open source, permissively", CH)
    name = serif("Apache-2.0", 72, bold=True).move_to([-3.6, 1.1, 0])
    lead = chip("leading choice · open decision 1", BUTTER, 19).next_to(name, m.DOWN, buff=0.3)
    alts = m.VGroup(text("alternatives:", 19, MUTED), chip("MIT", STONE, 19), chip("BSD-2-Clause", STONE, 19))
    alts.arrange(m.RIGHT, buff=0.2).next_to(lead, m.DOWN, buff=0.35)
    s.play(m.Write(name), run_time=1.2)
    s.play(m.FadeIn(lead, shift=m.UP * 0.1), m.FadeIn(alts, shift=m.UP * 0.1))
    points = bullets(
        [
            "Explicit patent grant suits a framework\ncompanies may build on",
            "Covers the core, the SDK, first-party\nplugins and the instance template",
            "Third-party plugins choose their own licence",
            "Settled before the first outside contribution;\nthe repo stays private until milestone 7",
        ],
        size=20,
        buff=0.32,
    ).move_to([3.3, 0.45, 0])
    s.play(m.LaggedStart(*[m.FadeIn(p, shift=m.LEFT * 0.1) for p in points], lag_ratio=0.2))
    files = ["LICENSE", "CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "CHANGELOG.md"]
    row = m.VGroup(*[chip(f, SAGE, 17, code=True) for f in files]).arrange(m.RIGHT, buff=0.2)
    cap = text("what the public repository carries", 17, MUTED)
    group = m.VGroup(cap, row).arrange(m.DOWN, buff=0.2).move_to([0, -2.6, 0])
    s.play(m.FadeIn(group, lag_ratio=0.1))


def hosted_slide(s: m.Scene) -> None:
    """The hosted service and a self-hosted instance side by side."""
    new_slide(
        s,
        "Hosted or self-hosted",
        notes="Plugins run in the bot's process with no sandbox, so the hosted service only "
        "runs plugins the maintainers reviewed. Anyone who wants custom code self-hosts.",
    )
    show_title(s, "Hosted service or your own clone", CH)
    cols = []
    specs = [
        (
            "Hosted teapot",
            SKY,
            [
                "Add the bot, enable plugins\nfrom a reviewed catalogue",
                "No custom code: plugins share\nthe process, unsandboxed",
                "Opens after quotas, OAuth,\nmember data deletion,\negress consent, privacy policy",
            ],
        ),
        (
            "Self-hosted instance",
            SAGE,
            [
                "Your own Discord application\nand bot identity",
                "Any plugin, including the\nones you write yourself",
                "You review what you install.\nCompose, or bare metal",
            ],
        ),
    ]
    for title, tone, items in specs:
        rect = box(6.1, 4.25, tone)
        head = serif(title, 30, bold=True)
        body = bullets(items, size=20, buff=0.3)
        inner = m.VGroup(head, body).arrange(m.DOWN, buff=0.35, aligned_edge=m.LEFT).move_to(rect)
        cols.append(m.VGroup(rect, inner))
    pair = m.VGroup(*cols).arrange(m.RIGHT, buff=0.6).move_to([0, -0.25, 0])
    s.play(m.FadeIn(pair[0], shift=m.RIGHT * 0.2), m.FadeIn(pair[1], shift=m.LEFT * 0.2))
    move = m.DoubleArrow(
        pair[0].get_bottom() + m.DOWN * 0.3 + m.RIGHT * 1.5,
        pair[1].get_bottom() + m.DOWN * 0.3 + m.LEFT * 1.5,
        color=MUTED,
        stroke_width=3,
        tip_length=0.16,
        buff=0,
    )
    later = text("later: guild export and import between instances, and out-of-process plugins", 18, MUTED)
    later.next_to(move, m.DOWN, buff=0.12)
    s.play(m.GrowFromCenter(move), m.FadeIn(later))


def _lock() -> m.VGroup:
    """A small padlock."""
    body = box(0.42, 0.34, BUTTER, radius=0.06)
    shackle = m.Arc(radius=0.14, start_angle=0, angle=m.PI, color=BUTTER.edge, stroke_width=4)
    shackle.next_to(body, m.UP, buff=0)
    return m.VGroup(shackle, body)


def _identity_rows() -> list[tuple[m.VGroup, m.VGroup, m.VGroup]]:
    """The three scenarios: their label, their picture and their verdict."""
    rows = []
    server = m.Circle(radius=0.55, fill_color=STONE.fill, fill_opacity=1, stroke_color=STONE.edge)
    a = avatar(SAGE.edge, "A", 0.3).next_to(server, m.LEFT, buff=0.25)
    b = avatar(LAVENDER.edge, "B", 0.3).next_to(server, m.RIGHT, buff=0.25)
    pic1 = m.VGroup(server, text("server", 20).move_to(server), a, b)
    rows.append(
        (
            card("Two teapots, one server", "different applications", 3.6, 1.25, BUTTER, 22, 19),
            pic1,
            m.VGroup(
                text(
                    "Two separate bots with their own commands.\nThey would fight over the same roles and features.",
                    18,
                ),
                text("Rule: one teapot per server.", 19, BUTTER.edge, bold=True),
            ).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.12),
        )
    )
    p1 = chip("process 1", SAGE, 16)
    p2 = chip("process 2", ROSE, 16)
    lock = _lock()
    pic2 = m.VGroup(p1, lock, p2).arrange(m.RIGHT, buff=0.3)
    rows.append(
        (
            card("Two processes, one token", "same database", 3.6, 1.25, SAGE, 22, 19),
            pic2,
            m.VGroup(
                text(
                    "The second cannot take the shard advisory locks\nin Postgres, so it refuses to start.",
                    18,
                ),
                text("Caught automatically.", 19, GOOD, bold=True),
            ).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.12),
        )
    )
    lap = m.VGroup(chip("laptop", STONE, 16), chip("db", SKY, 18)).arrange(m.DOWN, buff=0.08)
    drop = m.VGroup(chip("droplet", STONE, 16), chip("db", SKY, 18)).arrange(m.DOWN, buff=0.08)
    pic3 = m.VGroup(lap, text("?", 30, BAD, bold=True), drop).arrange(m.RIGHT, buff=0.3)
    rows.append(
        (
            card("One token, two databases", "dev laptop and production", 3.6, 1.25, ROSE, 22, 19),
            pic3,
            m.VGroup(
                text("Nothing can see the other process.\nBoth would answer every event.", 18),
                text("Guard: a separate dev bot application.", 19, BAD, bold=True),
            ).arrange(m.DOWN, aligned_edge=m.LEFT, buff=0.12),
        )
    )
    return rows


def identity_slide(s: m.Scene) -> None:
    """What happens when two bots, or two processes, compete for the same servers."""
    new_slide(
        s,
        "Bot identity and contention",
        notes="Each instance has its own Discord application, so its own bot id. Locks only "
        "see processes that share a database, which is why development uses its own app.",
    )
    show_title(s, "Bot identity and contention", CH)
    rows = zip(_identity_rows(), [1.35, -0.6, -2.55], strict=True)
    for n, ((label, pic, verdict), y) in enumerate(rows):
        label.move_to([-5.05, y, 0])
        pic.move_to([-1.35, y, 0])
        verdict.move_to([0.6, y, 0], aligned_edge=m.LEFT)
        s.play(m.FadeIn(label, shift=m.RIGHT * 0.1), m.FadeIn(pic), run_time=0.6)
        if n == 1:
            p2 = pic[2]
            home = p2.get_center()
            s.play(p2.animate.shift(m.LEFT * 0.25), run_time=0.3)
            mark = cross(BAD, 0.12).next_to(pic[1], m.UP, buff=0.08)
            s.play(p2.animate.move_to(home), m.FadeIn(mark), run_time=0.3)
        s.play(m.FadeIn(verdict, shift=m.LEFT * 0.1), run_time=0.6)


def _schema(name: str, role: str, tables: list[str], tone, width: float) -> m.VGroup:
    """A Postgres schema box with its role and tables."""
    rect = box(width, 2.75, tone)
    head = mono(name, 22)
    sub = text(role, 16, MUTED)
    chips = m.VGroup(*[chip(t, STONE, 15, code=True, pad=0.07) for t in tables])
    cols = 2 if len(tables) > 3 else 1
    chips.arrange_in_grid(cols=cols, buff=(0.15, 0.12))
    inner = m.VGroup(head, sub, chips).arrange(m.DOWN, buff=0.14).move_to(rect)
    return m.VGroup(rect, inner)


def database_slide(s: m.Scene) -> None:
    """One schema and role per plugin, guild_id everywhere, forward-only migrations."""
    new_slide(
        s,
        "The database",
        notes="Each plugin owns schema plugin_x and role teapot_plugin_x. The role has no "
        "rights on core or on other plugins, so a stray query fails at once. Every table "
        "has guild_id, which lets the core remove a server's data with no plugin code.",
    )
    show_title(s, "One Postgres, walled per plugin", CH)
    outer = box(13.2, 3.9, None).move_to([0, 0.75, 0])
    label = serif("Postgres", 22, MUTED, bold=True).next_to(outer.get_corner(m.UL), m.DR, buff=0.12)
    core = _schema(
        "core",
        "plugin roles have no rights here",
        ["guilds", "guild_plugins", "tokens", "audit_log", "audit_reads", "jobs", "migrations"],
        SKY,
        5.0,
    )
    ann = _schema("plugin_announcements", "role teapot_plugin_announcements", ["posts"], BUTTER, 3.6)
    gw = _schema("plugin_giveaways", "role teapot_plugin_giveaways", ["giveaways", "entries"], BUTTER, 3.6)
    schemas = m.VGroup(core, ann, gw).arrange(m.RIGHT, buff=0.3).move_to(outer).shift(m.UP * 0.05)
    s.play(m.FadeIn(outer), m.FadeIn(label))
    s.play(m.LaggedStart(*[m.FadeIn(x, shift=m.UP * 0.15) for x in schemas], lag_ratio=0.2))
    probe = m.CurvedArrow(gw[0].get_bottom(), core[0].get_bottom(), color=BAD, angle=-0.45)
    query = m.VGroup(
        mono("giveaways: SELECT * FROM core.tokens", 18, BAD),
        text("permission denied", 20, BAD, bold=True),
    ).arrange(m.RIGHT, buff=0.35)
    query.next_to(outer, m.DOWN, buff=0.2)
    s.play(m.Create(probe), m.FadeIn(query[0]), run_time=0.8)
    s.play(m.FadeIn(query[1]), m.Wiggle(core[1][0]))
    facts = bullets(
        [
            "Every table carries guild_id: 30 days after the bot leaves a server, its rows go, with no plugin code",
            "Forward-only numbered SQL migrations, one history per plugin, each file in one transaction",
            "Purging a plugin is DROP SCHEMA plugin_x CASCADE, and only the operator can do it",
        ],
        size=19,
        buff=0.2,
    ).move_to([0, -2.85, 0])
    s.play(m.LaggedStart(*[m.FadeIn(f, shift=m.UP * 0.1) for f in facts], lag_ratio=0.2))


def _guild_dots(n: int = 12) -> m.VGroup:
    """Coloured server dots, each colour one shard."""
    tones = [SAGE.edge, CLAY.edge, SKY.edge]
    dots = m.VGroup(*[m.Dot(radius=0.13, color=tones[i % 3]) for i in range(n)])
    return dots.arrange(m.RIGHT, buff=0.3)


def scaling_slide(s: m.Scene) -> None:
    """One process for all shards first, then shard clusters sharing Postgres."""
    new_slide(
        s,
        "Scaling",
        notes="Process memory only holds caches and work in flight. Everything that must be "
        "right across processes is a row in Postgres, so splitting needs no plugin changes.",
    )
    show_title(s, "Scaling: one process, then clusters", CH)
    dots = _guild_dots().move_to([-3.0, 1.65, 0])
    cap = text("servers, coloured by shard", 18, MUTED).next_to(dots, m.UP, buff=0.12)
    single = card("teapot run", "every shard, one process", 6.6, 1.2, SAGE, 24, 17).move_to([-3.0, 0.2, 0])
    pg = card("Postgres", "plans · jobs · config · tokens · locks", 6.6, 0.9, SKY, 22, 16).move_to([-3.0, -1.55, 0])
    s.play(m.FadeIn(dots, lag_ratio=0.05), m.FadeIn(cap))
    s.play(m.FadeIn(single), m.FadeIn(pg))
    feeds = m.VGroup(*[arrow(d.get_bottom(), [d.get_x(), single.get_top()[1], 0], buff=0.05) for d in dots])
    s.play(m.LaggedStart(*[m.GrowArrow(f) for f in feeds], lag_ratio=0.03), run_time=0.8)
    facts = bullets(
        [
            "One shard below 2,500 servers",
            "Members cached lazily: a big server\ncosts only its active members",
            "Past 100 servers, Discord verification\nand intent approval",
        ],
        size=19,
        buff=0.3,
    ).move_to([4.4, 0.6, 0])
    s.play(m.FadeIn(facts, lag_ratio=0.2))
    s.next_section("Shard clusters", notes="Each process owns the servers the formula gives it.")
    tones = [SAGE, CLAY, SKY]
    procs = m.VGroup(*[card(f"process {i + 1}", f"shard {i}", 2.0, 1.2, tones[i], 21, 16) for i in range(3)])
    procs.arrange(m.RIGHT, buff=0.3).move_to(single)
    s.play(m.FadeOut(feeds), m.ReplacementTransform(single, procs))
    shared = m.VGroup(*[arrow(p.get_bottom(), [p.get_x(), pg.get_top()[1], 0], buff=0.05) for p in procs])
    s.play(m.LaggedStart(*[m.GrowArrow(a) for a in shared], lag_ratio=0.1), run_time=0.6)
    order = sorted(range(len(dots)), key=lambda i: (i % 3, i))
    targets = []
    for slot, i in enumerate(order):
        shard, k = i % 3, slot % 4
        targets.append(dots[i].animate.move_to(procs[shard].get_top() + m.UP * 0.55 + m.RIGHT * (k - 1.5) * 0.4))
    s.play(*targets, run_time=1.2)
    formula = mono("shard = (guild_id >> 22) % shard_count", 19)
    formula.next_to(pg, m.DOWN, buff=0.35)
    more = bullets(
        ["Queue workers claim jobs with\nSKIP LOCKED, filtered by shard", "No plugin changes for the split"],
        size=19,
        buff=0.3,
    ).next_to(facts, m.DOWN, buff=0.45, aligned_edge=m.LEFT)
    s.play(m.Write(formula), m.FadeIn(more, lag_ratio=0.2))
