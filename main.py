import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from openai import AsyncAzureOpenAI
from starlette.middleware.base import BaseHTTPMiddleware

from auth import require_role
from foundry import classify_email, classify_intent
from models import BatchIn, BatchOut, ClassificationOut, EmailIn

load_dotenv()


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        obj = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj)

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_JsonFormatter())
logging.basicConfig(handlers=[_handler], level=logging.INFO, force=True)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — clients created once at startup, closed on shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # App Insights — one line; skipped if env var is absent
    if conn_str := os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(connection_string=conn_str)

    # All config read from env vars — nothing hardcoded
    credential = DefaultAzureCredential()

    # Managed identity token provider for Azure OpenAI — no API key needed
    token_provider = get_bearer_token_provider(
        credential, "https://cognitiveservices.azure.com/.default"
    )
    openai_client = AsyncAzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        azure_ad_token_provider=token_provider,
        api_version="2025-04-01-preview",
    )
    project_client = AIProjectClient(
        endpoint=os.environ["PROJECT_ENDPOINT"],
        credential=credential,
    )

    app.state.openai_client = openai_client
    app.state.project_client = project_client
    app.state.model = os.environ.get("MODEL_DEPLOYMENT", "o4-mini")
    app.state.agent_name = os.environ["AGENT_NAME"]
    app.state.agent_version = os.environ.get("AGENT_VERSION", "1")

    logger.info("startup complete")
    yield
    await openai_client.close()
    logger.info("shutdown complete")


app = FastAPI(title="Email Intelligence API", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Middleware — MIME type + request size validation
# ---------------------------------------------------------------------------

_MAX_BODY_BYTES = 1_048_576  # 1 MB

class _ValidationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            content_type = request.headers.get("content-type", "")
            if not content_type.startswith("application/json"):
                return JSONResponse(
                    status_code=415,
                    content={"detail": "Content-Type must be application/json"},
                )
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > _MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body exceeds 1 MB limit"},
                )
        return await call_next(request)

app.add_middleware(_ValidationMiddleware)


# ---------------------------------------------------------------------------
# Global exception handler — never expose a stack trace to callers
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def _global_exc_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled_exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root() -> dict:
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict:
    """Ingress/liveness probe — always returns 200 if the process is alive."""
    return {"status": "ok"}


@app.post("/classify", response_model=ClassificationOut)
async def classify(
    email: EmailIn,
    request: Request,
    _claims: dict = Depends(require_role("Email.Classify")),
) -> ClassificationOut:
    """Classify intent only. No reply is generated."""
    logger.info(json.dumps({"event": "classify", "message_id": email.message_id}))
    result = await classify_intent(
        openai_client=request.app.state.openai_client,
        model=request.app.state.model,
        email=email,
    )
    logger.info(json.dumps({"event": "classify_done", "message_id": email.message_id, "status": result.status, "latency_ms": result.latency_ms}))
    return result


@app.post("/respond", response_model=ClassificationOut)
async def respond(
    email: EmailIn,
    request: Request,
    _claims: dict = Depends(require_role("Email.Classify")),
) -> ClassificationOut:
    """Classify intent AND generate a customer reply via the RAG agent."""
    logger.info(json.dumps({"event": "respond", "message_id": email.message_id}))
    result = await classify_email(
        openai_client=request.app.state.openai_client,
        project_client=request.app.state.project_client,
        model=request.app.state.model,
        agent_name=request.app.state.agent_name,
        agent_version=request.app.state.agent_version,
        email=email,
    )
    logger.info(json.dumps({"event": "respond_done", "message_id": email.message_id, "status": result.status, "latency_ms": result.latency_ms}))
    return result


async def classify_batch(batch_in: BatchIn, request: Request) -> BatchOut:
    """Process multiple emails concurrently through the full pipeline."""
    tasks = [
        classify_email(
            openai_client=request.app.state.openai_client,
            project_client=request.app.state.project_client,
            model=request.app.state.model,
            agent_name=request.app.state.agent_name,
            agent_version=request.app.state.agent_version,
            email=email,
        )
        for email in batch_in.emails
    ]
    results = list(await asyncio.gather(*tasks))
    failed = sum(1 for r in results if r.status != "success")
    return BatchOut(results=results, processed=len(results), failed=failed)
