from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://routeon:routeon@db:5432/routeon"
    KAKAO_API_KEY: str = ""
    EX_API_KEY: str = ""
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"
    DEBUG: bool = False

    model_config = {"env_file": ".env"}


settings = Settings()
