import os
import sys

# Must be before any local import — config.py reads these at import time.
os.environ.setdefault("PROJECT_ENDPOINT", "https://test.services.ai.azure.com/api/projects/test")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://test.openai.azure.com/openai/v1")
os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("AGENT_NAME", "rag-test")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from models import EmailIn  # noqa: E402


def make_email(**overrides) -> EmailIn:
    defaults = {
        "message_id": "MSG-001",
        "subject": "Cannot log in to net banking",
        "body": "I have been unable to log in since this morning.",
    }
    defaults.update(overrides)
    return EmailIn(**defaults)


def make_openai_client(output_text: str = "") -> MagicMock:
    response = MagicMock()
    response.output_text = output_text

    client = MagicMock()
    client.responses = MagicMock()
    client.responses.create = AsyncMock(return_value=response)
    client.close = AsyncMock()
    return client


def make_project_client(agent_output: str = "Thank you for contacting us.") -> MagicMock:
    agent_response = MagicMock()
    agent_response.output_text = agent_output

    inner_openai = MagicMock()
    inner_openai.responses = MagicMock()
    inner_openai.responses.create = MagicMock(return_value=agent_response)

    project_client = MagicMock()
    project_client.get_openai_client = MagicMock(return_value=inner_openai)
    return project_client


GOOD_CLASSIFICATION_JSON = """{
  "intent": "netbanking_access_issue",
  "confidence": 0.91,
  "sub_intent": "login_failure",
  "priority": "high",
  "summary": "Customer cannot log into net banking."
}"""

AGENT_REPLY = "Dear Customer, we are sorry to hear you are having trouble. Please try resetting your password."
