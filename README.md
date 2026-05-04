# Agentic Gateway — Phase 2

A production-ready local gateway that accepts multimodal input, classifies intent with a local LLM, and routes to the correct backend.

---

## Architecture

```
POST /ingest
     │
     ▼
┌─────────────┐
│  ingestion  │  normalise(), validate modality-specific content
└──────┬──────┘
       │  NormalisedEnvelope
       ▼
┌─────────────────┐
│ classification  │  Ollama (temp=0, max_tokens=5) → one of four tokens
└──────┬──────────┘
       │  RoutingTarget
       ▼
┌─────────────────────────────────────────────┐
│              dispatch (routing switch)       │
│                                             │
│  LOCAL_TOOLS → tools.execute()              │
│  LOCAL_LLM   → routing.route_local_llm()   │
│  CLOUD_LLM   → routing.route_cloud_llm()   │
│  DROP        → return immediately           │
└─────────────────────────────────────────────┘
```

### Routing Targets

| Target | When used | Backend |
|---|---|---|
| `LOCAL_TOOLS` | Deterministic actions: Radarr, Sonarr, SABnzbd, file ops | Explicit function registry |
| `LOCAL_LLM` | Simple Q&A, summarisation, reasoning within local model capacity | Ollama |
| `CLOUD_LLM` | Complex reasoning, coding, large context, external knowledge | OpenRouter |
| `DROP` | Empty, malformed, unsafe, or unclassifiable input | — |

---

## Files

```
gateway/
├── main.py            # FastAPI app, auth middleware, /ingest endpoint
├── config.py          # All configuration (env vars with defaults)
├── models.py          # All Pydantic schemas
├── ingestion.py       # Normalisation and content validation
├── classification.py  # Ollama-based intent classifier
├── routing.py         # LOCAL_LLM and CLOUD_LLM backends
├── tools.py           # Tool registry and execution (Radarr, Sonarr, SABnzbd)
├── dispatch.py        # Pipeline orchestrator (classify → route)
├── requirements.txt
└── .env.example
```

---

## Quickstart

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — at minimum set GATEWAY_API_KEY and OLLAMA_URL

# 3. Run
python main.py
# or: uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## Usage

### Health check (no auth required)
```bash
curl http://localhost:8000/health
```

### Text → LOCAL_TOOLS (add a movie via Radarr)
```bash
curl -X POST http://localhost:8000/ingest \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secret-key" \
     -d '{"modality":"text","content":"add movie inception","source_device":"phone"}'
```

### Text → CLOUD_LLM
```bash
curl -X POST http://localhost:8000/ingest \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secret-key" \
     -d '{"modality":"text","content":"Explain the tradeoffs between ZFS and Btrfs for a homelab NAS","source_device":"desktop"}'
```

### Device event → LOCAL_TOOLS
```bash
curl -X POST http://localhost:8000/ingest \
     -H "Content-Type: application/json" \
     -H "X-API-Key: your-secret-key" \
     -d '{"modality":"event","content":{"action":"pause download","trigger":"motion_sensor","room":"office"},"source_device":"pi-sensor"}'
```

---

## Extending

### Add a new tool
1. Write `async def my_tool(args: dict) -> ToolResult` in `tools.py`.
2. Register it in `_TOOL_REGISTRY`.
3. Add keyword → key mappings in `_INTENT_MAP`.

### Add a new routing target
1. Add the token to `RoutingTarget` in `models.py` and `ALLOWED_ROUTING_TOKENS`.
2. Add a case to the `match` block in `dispatch.py`.
3. Update the classifier system prompt in `classification.py`.

### Swap the classifier backend
Replace `_call_ollama()` in `classification.py`. The function signature and
return contract are the only things `classify()` depends on.

---

## Security notes

- All requests except `/health` require a valid `X-API-Key` header.
- The classifier enforces a hard token allowlist — freeform output is never acted on.
- Tool execution uses an explicit registry — no shell exec, no dynamic eval.
- No raw bytes are forwarded to LLM backends (image/voice content is described, not sent).
- Set `GATEWAY_HOST` to your Tailscale IP to avoid binding to all interfaces.
