from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    yutori_api_key: str = ""
    reka_api_key: str = ""
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    headless: bool = True
    screenshot_dir: str = "/tmp/friendly-screenshots"
    log_level: str = "INFO"
    n1_model: str = "n1"
    n1_base_url: str = "https://api.yutori.com/v1"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
