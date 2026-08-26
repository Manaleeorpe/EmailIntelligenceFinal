import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from conftest import (
    AGENT_REPLY,
    GOOD_CLASSIFICATION_JSON,
    make_email,
    make_openai_client,
    make_project_client,
)
from foundry import classify_email
from models import BatchIn, ClassificationOut


# ---------------------------------------------------------------------------
# classify_email — both LLM calls mocked
# ---------------------------------------------------------------------------

async def test_happy_path():
    email = make_email()
    openai_client = make_openai_client(output_text=GOOD_CLASSIFICATION_JSON)
    project_client = make_project_client(agent_output=AGENT_REPLY)

    result = await classify_email(
        openai_client=openai_client,
        project_client=project_client,
        model="o4-mini",
        agent_name="rag-test",
        agent_version="2",
        email=email,
    )

    assert result.status == "success"
    assert result.message_id == "MSG-001"
    assert result.intent == "netbanking_access_issue"
    assert result.confidence == 0.91
    assert result.sub_intent == "login_failure"
    assert result.priority == "high"
    assert result.summary == "Customer cannot log into net banking."
    assert result.email_response == AGENT_REPLY
    assert result.latency_ms >= 0


async def test_classify_call_receives_email_content():
    """o4-mini call must include subject and body — never log them, but must send them."""
    email = make_email(subject="Card blocked", body="My debit card is blocked.")
    openai_client = make_openai_client(output_text=GOOD_CLASSIFICATION_JSON)
    project_client = make_project_client()

    await classify_email(
        openai_client=openai_client,
        project_client=project_client,
        model="o4-mini",
        agent_name="rag-test",
        agent_version="2",
        email=email,
    )

    call_args = openai_client.responses.create.call_args
    input_messages = call_args.kwargs["input"]
    user_content = next(m["content"] for m in input_messages if m["role"] == "user")
    assert "Card blocked" in user_content
    assert "My debit card is blocked." in user_content


async def test_bad_json_from_llm_returns_parse_error():
    openai_client = make_openai_client(output_text="Sorry, I cannot classify this.")
    project_client = make_project_client()

    result = await classify_email(
        openai_client=openai_client,
        project_client=project_client,
        model="o4-mini",
        agent_name="rag-test",
        agent_version="2",
        email=make_email(),
    )

    assert result.message_id == "MSG-001"
    assert result.intent == "parse_error"
    assert "parse_error" in result.status


async def test_llm_call_failure_returns_failed_status():
    openai_client = MagicMock()
    openai_client.responses = MagicMock()
    openai_client.responses.create = AsyncMock(side_effect=RuntimeError("network error"))

    result = await classify_email(
        openai_client=openai_client,
        project_client=make_project_client(),
        model="o4-mini",
        agent_name="rag-test",
        agent_version="2",
        email=make_email(),
    )

    assert result.message_id == "MSG-001"
    assert result.status.startswith("failed")
    assert result.confidence == 0.0


async def test_agent_call_failure_returns_failed_status():
    openai_client = make_openai_client(output_text=GOOD_CLASSIFICATION_JSON)

    broken_project = MagicMock()
    broken_inner = MagicMock()
    broken_inner.responses.create = MagicMock(side_effect=RuntimeError("agent down"))
    broken_project.get_openai_client = MagicMock(return_value=broken_inner)

    result = await classify_email(
        openai_client=openai_client,
        project_client=broken_project,
        model="o4-mini",
        agent_name="rag-test",
        agent_version="2",
        email=make_email(),
    )

    assert result.message_id == "MSG-001"
    assert result.status.startswith("failed")


# ---------------------------------------------------------------------------
# Batch — partial failure
# ---------------------------------------------------------------------------

async def test_batch_partial_failure():
    """Email 1 succeeds; Email 2 fails. processed=2, failed=1."""
    success = ClassificationOut(
        message_id="MSG-001",
        intent="netbanking_access_issue",
        confidence=0.91,
        latency_ms=120,
        status="success",
    )
    failure = ClassificationOut(
        message_id="MSG-002",
        intent="unknown",
        confidence=0.0,
        latency_ms=50,
        status="failed: RuntimeError",
    )
    responses = {"MSG-001": success, "MSG-002": failure}

    async def mock_classify(openai_client, project_client, model, agent_name, agent_version, email):
        return responses[email.message_id]

    import main as main_module

    mock_request = MagicMock()
    mock_request.app.state.openai_client = MagicMock()
    mock_request.app.state.project_client = MagicMock()
    mock_request.app.state.model = "o4-mini"
    mock_request.app.state.agent_name = "rag-test"
    mock_request.app.state.agent_version = "2"

    batch_in = BatchIn(
        emails=[
            make_email(message_id="MSG-001"),
            make_email(message_id="MSG-002"),
        ]
    )

    with patch.object(main_module, "classify_email", side_effect=mock_classify):
        result = await main_module.classify_batch(batch_in, mock_request)

    assert result.processed == 2
    assert result.failed == 1
    by_id = {r.message_id: r for r in result.results}
    assert by_id["MSG-001"].status == "success"
    assert by_id["MSG-002"].status != "success"
