"""Settings and logging (WP1.2)."""

import json
import logging
import os
from pathlib import Path

import pytest

from teabot.logs import JsonFormatter, TextFormatter, setup_logging
from teabot.settings import Settings, load_settings

TEMPLATE = Path(__file__).parents[1] / "template" / "teabot.env.example"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("TEABOT_"):
            monkeypatch.delenv(name)


def test_env_file_and_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / "teabot.env"
    env.write_text("TEABOT_DISCORD_TOKEN=from-file\nTEABOT_DB_PORT=6000\n")
    monkeypatch.setenv("TEABOT_DB_PORT", "7000")
    settings = load_settings(env)
    assert settings.discord_token.get_secret_value() == "from-file"
    assert settings.db_port == 7000


def test_disabled_plugins_is_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEABOT_DISCORD_TOKEN", "t")
    monkeypatch.setenv("TEABOT_DISABLED_PLUGINS", " devtools, giveaways ,,")
    assert load_settings(None).disabled_plugins == ("devtools", "giveaways")


def test_secrets_do_not_print(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEABOT_DISCORD_TOKEN", "very-secret")
    assert "very-secret" not in repr(load_settings(None))


def test_log_format_follows_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEABOT_DISCORD_TOKEN", "t")
    assert load_settings(None).resolved_log_format == "json"
    monkeypatch.setenv("TEABOT_DEV_MODE", "true")
    assert load_settings(None).resolved_log_format == "text"


def test_template_lists_every_setting() -> None:
    listed = {
        line.split("=", 1)[0].removeprefix("TEABOT_").lower()
        for line in TEMPLATE.read_text().splitlines()
        if line.startswith("TEABOT_")
    }
    assert listed == set(Settings.model_fields)


def test_json_formatter_carries_extra_fields() -> None:
    record = logging.LogRecord("teabot.test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.guild_id = 42
    entry = json.loads(JsonFormatter().format(record))
    assert entry["message"] == "hello world"
    assert entry["guild_id"] == 42
    assert entry["level"] == "INFO"


def test_json_logs_leave_out_standard_and_private_attributes() -> None:
    record = logging.LogRecord("teabot.test", logging.INFO, __file__, 7, "hi", (), None)
    record._hidden = "x"
    entry = json.loads(JsonFormatter().format(record))
    assert set(entry) == {"time", "level", "logger", "message"}


@pytest.mark.parametrize(("fmt", "json_lines"), [("json", True), ("text", False)])
def test_setup_logging_picks_the_formatter(fmt: str, json_lines: bool) -> None:
    setup_logging("INFO", fmt)  # type: ignore[arg-type]
    try:
        (handler,) = logging.getLogger().handlers
        assert isinstance(handler.formatter, JsonFormatter) is json_lines
    finally:
        logging.getLogger().handlers.clear()


def test_text_logs_show_extra_fields_after_the_message() -> None:
    record = logging.LogRecord("teabot.test", logging.ERROR, __file__, 1, "teabot stopped", (), None)
    record.reason = "discord stopped: ShardOwnedError()"
    line = TextFormatter().format(record)
    assert line.endswith("teabot stopped reason='discord stopped: ShardOwnedError()'")


def test_text_logs_without_extras_are_unchanged() -> None:
    record = logging.LogRecord("teabot.test", logging.INFO, __file__, 1, "plain", (), None)
    assert TextFormatter().format(record).endswith("teabot.test: plain")


def test_uvicorns_colour_copy_of_the_message_is_left_out() -> None:
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "Started server", (), None)
    record.color_message = "Started \x1b[36mserver\x1b[0m"
    assert TextFormatter().format(record).endswith("uvicorn.error: Started server")
    assert "color_message" not in json.loads(JsonFormatter().format(record))
