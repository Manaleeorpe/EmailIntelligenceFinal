import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    project_endpoint: str
    azure_openai_endpoint: str
    api_key: str
    agent_name: str
    agent_version: str
    model_deployment: str
    log_level: str

    def __init__(self) -> None:
        missing: list[str] = []

        self.project_endpoint = os.environ.get("PROJECT_ENDPOINT", "").strip()
        self.azure_openai_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
        self.api_key = os.environ.get("API_KEY", "").strip()
        self.agent_name = os.environ.get("AGENT_NAME", "").strip()
        self.agent_version = os.environ.get("AGENT_VERSION", "1").strip()
        self.model_deployment = os.environ.get("MODEL_DEPLOYMENT", "o4-mini").strip()
        self.log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

        if not self.project_endpoint:
            missing.append("PROJECT_ENDPOINT")
        if not self.azure_openai_endpoint:
            missing.append("AZURE_OPENAI_ENDPOINT")
        if not self.api_key:
            missing.append("API_KEY")
        if not self.agent_name:
            missing.append("AGENT_NAME")

        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}"
            )


settings = Settings()
