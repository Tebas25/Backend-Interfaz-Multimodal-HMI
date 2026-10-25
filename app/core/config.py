from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Bartender Multimodal HMI"
    PROJECT_VERSION: str = "1.0.0"
    get_catalog_url: str
    micro_url: str
    kong_auth_key: str

    model_config = {"env_file": ".env"}


settings = Settings()
