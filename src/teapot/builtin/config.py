"""The core admin plugin's config (D24, plan): the core's own per-server settings, stored like any plugin's."""

from pydantic import BaseModel, ConfigDict

from teapot.sdk import ChannelRef


class AdminConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    log_channel_id: ChannelRef | None = None
