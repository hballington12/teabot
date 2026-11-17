"""Discord's permission names, as `needs=` takes them and `Role.permissions` gives them."""

from typing import Literal

type Permission = Literal[
    "add_reactions", "administrator", "attach_files", "ban_members", "bypass_slowmode", "change_nickname",
    "connect", "create_events", "create_expressions", "create_instant_invite", "create_polls",
    "create_private_threads", "create_public_threads", "deafen_members", "embed_links", "external_emojis",
    "external_stickers", "kick_members", "manage_channels", "manage_emojis", "manage_emojis_and_stickers",
    "manage_events", "manage_expressions", "manage_guild", "manage_messages", "manage_nicknames",
    "manage_permissions", "manage_roles", "manage_threads", "manage_webhooks", "mention_everyone",
    "moderate_members", "move_members", "mute_members", "pin_messages", "priority_speaker",
    "read_message_history", "read_messages", "request_to_speak", "send_messages", "send_messages_in_threads",
    "send_polls", "send_tts_messages", "send_voice_messages", "set_voice_channel_status", "speak", "stream",
    "use_application_commands", "use_embedded_activities", "use_external_apps", "use_external_emojis",
    "use_external_sounds", "use_external_stickers", "use_soundboard", "use_voice_activation", "view_audit_log",
    "view_channel", "view_creator_monetization_analytics", "view_guild_insights",
]  # fmt: skip
"""A Discord permission a member needs for an action, by discord.py's name for it."""

DANGEROUS: frozenset[Permission] = frozenset(
    {
        "administrator",
        "ban_members",
        "kick_members",
        "manage_channels",
        "manage_events",
        "manage_expressions",
        "manage_guild",
        "manage_messages",
        "manage_nicknames",
        "manage_roles",
        "manage_threads",
        "manage_webhooks",
        "mention_everyone",
        "moderate_members",
        "move_members",
        "mute_members",
        "deafen_members",
        "view_audit_log",
    }
)
"""Permissions that let a member act on others or on the server: a role pickers never offer, and that role
changes through an AI assistant's token never give or take."""
