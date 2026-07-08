from pydantic import BaseModel


class ModelProviderProfile(BaseModel):
    provider_id: str
    provider_type: str
    display_name: str = "Active Model Provider"
    base_url: str = ""
    auth_type: str = "none"
    api_key_ref: str = ""
    default_model: str
    enabled: bool = True
    created_by: str = "system"
    notes: str = ""
