from pathlib import Path
from pydantic_settings import BaseSettings

# .env 파일은 이 파일(config.py)과 같은 backend/ 폴더 기준으로 탐색
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://routeon:routeon@db:5432/routeon"
    KAKAO_API_KEY: str = ""
    EX_API_KEY: str = ""
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION"
    DEBUG: bool = False

    model_config = {"env_file": str(_ENV_FILE)}


settings = Settings()
