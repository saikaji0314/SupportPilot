from pydantic import BaseModel


class Observation(BaseModel):
    wifi_connected: bool | None = None
    others_affected: bool | None = None
    setup_complete: bool | None = None
