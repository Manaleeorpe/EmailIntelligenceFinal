import json
import time

from models import ClassificationOut, EmailIn

# The LLM returns structured data because the system prompt forces JSON-only output.
# response.output_text is raw text — we parse it with json.loads().
# No special API feature is used; prompt engineering is the mechanism.
_SYSTEM_PROMPT = """\
You are a banking customer-support email classifier.
Return ONLY valid JSON — no markdown, no explanation:
{
  "intent": "<netbanking_access_issue | account_inquiry | transaction_dispute | card_management | fraud_report | payment_failure | general_inquiry | other>",
  "confidence": <float 0.0-1.0>,
  "sub_intent": "<string or null>",
  "priority": "<high | medium | low | null>",
  "summary": "<one-sentence description or null>"
}"""


async def classify_intent(
    openai_client,
    model: str,
    email: EmailIn,
) -> ClassificationOut:
    """Call the LLM to classify the email. No reply is generated."""
    start = time.monotonic()
    user_content = f"Subject: {email.subject}\n\nBody:\n{email.body}"

    try:
        response = await openai_client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )

        try:
            data = json.loads(response.output_text)
        except (json.JSONDecodeError, ValueError):
            return ClassificationOut(
                message_id=email.message_id,
                intent="parse_error",
                confidence=0.0,
                latency_ms=int((time.monotonic() - start) * 1000),
                status="parse_error",
            )

        return ClassificationOut(
            message_id=email.message_id,
            intent=data.get("intent", "unknown"),
            confidence=float(data.get("confidence", 0.0)),
            sub_intent=data.get("sub_intent"),
            priority=data.get("priority"),
            summary=data.get("summary"),
            latency_ms=int((time.monotonic() - start) * 1000),
            status="success",
        )

    except Exception as exc:
        return ClassificationOut(
            message_id=email.message_id,
            intent="unknown",
            confidence=0.0,
            latency_ms=int((time.monotonic() - start) * 1000),
            status=f"failed: {type(exc).__name__}",
        )


async def classify_email(
    openai_client,
    project_client,
    model: str,
    agent_name: str,
    agent_version: str,
    email: EmailIn,
) -> ClassificationOut:
    """Classify the email, then generate a customer reply via the RAG agent.

    Two calls, sequential:
      1. LLM (async) — returns structured JSON parsed into classification fields.
      2. Foundry agent (sync) — returns the drafted reply in output_text.
    """
    start = time.monotonic()
    user_content = f"Subject: {email.subject}\n\nBody:\n{email.body}"

    try:
        # --- Step 1: classify with the LLM (async) ---
        response = await openai_client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )

        try:
            data = json.loads(response.output_text)
        except (json.JSONDecodeError, ValueError):
            return ClassificationOut(
                message_id=email.message_id,
                intent="parse_error",
                confidence=0.0,
                latency_ms=int((time.monotonic() - start) * 1000),
                status="parse_error",
            )

        # --- Step 2: generate reply via Foundry RAG agent (sync) ---
        agent_client = project_client.get_openai_client()
        agent_response = agent_client.responses.create(
            input=[{"role": "user", "content": user_content}],
            extra_body={
                "agent_reference": {
                    "name": agent_name,
                    "version": agent_version,
                    "type": "agent_reference",
                }
            },
        )

        return ClassificationOut(
            message_id=email.message_id,
            intent=data.get("intent", "unknown"),
            confidence=float(data.get("confidence", 0.0)),
            sub_intent=data.get("sub_intent"),
            priority=data.get("priority"),
            summary=data.get("summary"),
            email_response=agent_response.output_text,
            latency_ms=int((time.monotonic() - start) * 1000),
            status="success",
        )

    except Exception as exc:
        return ClassificationOut(
            message_id=email.message_id,
            intent="unknown",
            confidence=0.0,
            latency_ms=int((time.monotonic() - start) * 1000),
            status=f"failed: {type(exc).__name__}",
        )
