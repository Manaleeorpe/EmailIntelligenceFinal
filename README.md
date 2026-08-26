# Email Intelligence API

A production-ready AI microservice that classifies banking customer support emails and auto-generates professional replies using Azure OpenAI and Azure AI Foundry RAG agents.

---

## What It Does

When a customer sends an email to the bank, this API:

1. **Classifies** the email — identifies intent (e.g. `netbanking_access_issue`), confidence score, priority, and a one-line summary using Azure OpenAI (`o4-mini`)
2. **Generates a reply** — drafts a professional customer response using a RAG agent in Azure AI Foundry that has access to the bank's knowledge base
3. **Returns structured output** — everything in a clean JSON response ready to feed into a Logic App, Power Automate, or any downstream system

The LLM returns structured data because the system prompt forces JSON-only output — no special API feature, just prompt engineering parsed with `json.loads()`.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI + Uvicorn |
| AI classification | Azure OpenAI (`o4-mini`) via Responses API |
| Reply generation | Azure AI Foundry RAG Agent |
| Auth (outbound) | Azure Managed Identity + `DefaultAzureCredential` |
| Input validation | Pydantic v2 (field validators, size limits) |
| Request middleware | Content-Type + 1 MB size enforcement |
| Logging | Structured JSON logs (App Insights ready) |
| Observability | Azure Monitor OpenTelemetry |
| Containerisation | Docker |
| Hosting | Azure Container Apps (Consumption plan) |
| Registry | Docker Hub (authenticated pulls) |
| CI/CD | GitHub Actions |
| Testing | pytest + pytest-asyncio (fully mocked, no Azure calls) |
| Language | Python 3.12 |

---

## Architecture

```
Customer Email
      │
      ▼
Azure Logic App / Power Automate
      │  HTTP POST
      ▼
Container App (FastAPI)
  ├── POST /classify   ──▶  Azure OpenAI (o4-mini)
  │                         returns: intent, confidence, priority, summary
  │
  └── POST /respond    ──▶  Azure OpenAI (o4-mini)  ──▶  classification
                       ──▶  AI Foundry RAG Agent     ──▶  drafted reply
```

---

## API Endpoints

| Endpoint | Input | Output |
|---|---|---|
| `POST /classify` | Email (subject, body, sender) | Intent, confidence, priority, summary |
| `POST /respond` | Email (subject, body, sender) | Above + AI-drafted customer reply |
| `GET /health` | — | `{"status": "ok"}` |

**Sample request:**
```json
{
  "message_id": "MSG-001",
  "subject": "Cannot login to net banking",
  "body": "I have been unable to log in since this morning.",
  "sender": "customer@gmail.com",
  "received_at": "2026-08-17T11:05:33.943Z",
  "has_attachments": false
}
```

**Sample response (`/respond`):**
```json
{
  "message_id": "MSG-001",
  "intent": "netbanking_access_issue",
  "confidence": 0.93,
  "sub_intent": "login_failure",
  "priority": "high",
  "summary": "Customer cannot log into net banking since morning.",
  "email_response": "Dear Customer, we apologise for the inconvenience...",
  "latency_ms": 2100,
  "status": "success"
}
```

---

## Project Structure

```
├── main.py          # FastAPI app, lifespan, middleware, routes
├── foundry.py       # LLM classification + RAG agent reply logic
├── models.py        # Pydantic models with validation
├── config.py        # Env var loader
├── Dockerfile
├── requirements.txt
└── tests/
    ├── conftest.py       # Shared mocks and fixtures
    └── test_classify.py  # Unit tests (happy path, failures, batch)
```

---

## Local Setup

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env`:
```
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
API_KEY=your-key                    # local dev only — not used in production
PROJECT_ENDPOINT=https://your-resource.services.ai.azure.com/api/projects/your-project
AGENT_NAME=rag-test
AGENT_VERSION=2
MODEL_DEPLOYMENT=o4-mini
```

```bash
uvicorn main:app --reload --port 8000
# Test at http://localhost:8000/docs
```

---

## Run Tests

```bash
pytest tests/ -v
```

All tests are fully mocked — no Azure connection required.

---

## Docker

```bash
docker build -t your-dockerhub/email-intelligence:v1 .
docker push your-dockerhub/email-intelligence:v1
```

---

## Azure Deployment

### 1. Create Container App

```bash
az containerapp create \
  --name fastapi-app \
  --resource-group rg-fastapi \
  --image docker.io/your-dockerhub/email-intelligence:v1 \
  --target-port 8000 \
  --ingress external \
  --system-assigned
```

### 2. Set Environment Variables

```bash
az containerapp update --name fastapi-app --resource-group rg-fastapi \
  --set-env-vars \
  AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com" \
  PROJECT_ENDPOINT="https://your-resource.services.ai.azure.com/api/projects/your-project" \
  AGENT_NAME="rag-test" \
  AGENT_VERSION="2" \
  MODEL_DEPLOYMENT="o4-mini"
```

### 3. Docker Hub Credentials (avoids rate limiting)

```bash
az containerapp registry set \
  --name fastapi-app --resource-group rg-fastapi \
  --server index.docker.io \
  --username your-dockerhub-username \
  --password your-dockerhub-token
```

---

## Managed Identities — Two Separate Identities

Two identities are needed because the Container App calls **outbound** to Azure AI, and Logic Apps calls **inbound** to the Container App — two different services, two different directions.

```
Logic App ──(Identity 2)──▶ Container App ──(Identity 1)──▶ Azure OpenAI / AI Foundry
```

### Identity 1 — Container App → Azure AI (active)

Allows the container to call Azure AI services without any API key in production.

```bash
# Get principal ID
az containerapp identity show --name fastapi-app --resource-group rg-fastapi --query principalId -o tsv

# Azure OpenAI access
az role assignment create \
  --assignee <principalId> \
  --role "Cognitive Services OpenAI User" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<openai-resource>

# Azure AI Foundry access
az role assignment create \
  --assignee <principalId> \
  --role "Azure AI Developer" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>
```

### Identity 2 — Logic App → Container App (when securing the endpoint)

```bash
# Lock down the Container App endpoint
az containerapp auth microsoft update \
  --name fastapi-app --resource-group rg-fastapi \
  --client-id <app-registration-client-id> \
  --issuer https://login.microsoftonline.com/<tenant-id>/v2.0 \
  --unauthenticated-client-action Return401
```

Then in Logic App → Identity → System assigned → On, and configure the HTTP action:
```
Authentication: Managed Identity
Audience:       api://<app-registration-client-id>
```

---

## Authentication vs Authorization

| | What it means | Status |
|---|---|---|
| **Authentication** | Proving who the caller is | Identity 1 active; Identity 2 not yet set up |
| **Authorization** | What the caller is allowed to do | Not implemented — endpoint is public |

Even after adding Identity 2 (Easy Auth), you only know WHO is calling — not WHAT they can do. Full authorization would require one of:

| Approach | Description |
|---|---|
| **Azure AD App Roles** | Define roles like `Email.Classify`, assign to callers, verify in FastAPI middleware |
| **API Management (APIM)** | Put APIM in front — handles auth, authz, rate limiting without touching app code |
| **JWT claim checks** | Inspect token claims inside FastAPI and reject unauthorized callers |

For production banking, APIM is the standard approach.

---

## CI/CD — GitHub Actions

Every push to `main` automatically builds, pushes, and deploys.

```yaml
# .github/workflows/deploy.yml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: your-dockerhub/email-intelligence:latest

      - name: Azure Login
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}

      - name: Deploy to Container App
        run: |
          az containerapp update \
            --name fastapi-app \
            --resource-group rg-fastapi \
            --image docker.io/your-dockerhub/email-intelligence:latest
```

**GitHub Secrets required:**

| Secret | How to get |
|---|---|
| `DOCKERHUB_USERNAME` | Your Docker Hub username |
| `DOCKERHUB_TOKEN` | Docker Hub → Account Settings → Personal Access Tokens |
| `AZURE_CREDENTIALS` | `az ad sp create-for-rbac --name github-actions --role contributor --scope /subscriptions/<sub-id>/resourceGroups/rg-fastapi --sdk-auth` |

---

## Key Design Decisions

| Decision | Reason |
|---|---|
| Managed identity over API keys | No secrets to rotate or leak in production |
| Sequential LLM calls (not concurrent) | Agent is only called if classification succeeds — saves cost and latency on failures |
| Prompt engineering for structured output | Simpler than JSON schema mode; `json.loads()` on `response.output_text` |
| FastAPI over Flask | Native async support matches the async Azure SDK calls |
| All tests mocked | Tests run in CI with no Azure credentials required |
| Pydantic validators on input | Rejects oversized payloads before they reach the LLM |
