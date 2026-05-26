import json
import os
import queue
import threading
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import DATA_DIR, ROOT_DIR, get_settings
from app.db.database import get_database_backend, initialize_database
from app.db.repository import PromptRepository
from app.model_profiles import profile_for_model
from app.pipeline import PromptOptimizationPipeline
from app.schemas import (
    ApiKeyCreateRequest,
    ApiKeyVerifyRequest,
    FeedbackRequest,
    OptimizeRequest,
    OptimizeResponse,
    PublicOptimizeRequest,
    OpenRouterKeyRequest,
)
from app.security import safe_error_message
from app.services.hermes_adapter import HermesAdapter
from app.services.openrouter_client import OpenRouterClient
from app.utils.json_tools import derive_title


repository = PromptRepository()
STARTED_AT = datetime.now(timezone.utc).isoformat()


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    repository.redact_stored_sensitive_data()
    yield


app = FastAPI(title="Hermes Prompt Optimizer (OpenRouter)", version="0.6.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Localhost-only desktop tool. The UI is served same-origin, but the backend
    # runs on different ports in different modes (8060 desktop, 8050 supervised,
    # or a custom supervisor port), so match any localhost port instead of one.
    allow_origin_regex=r"http://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    client = OpenRouterClient(settings)
    selected_model = client.select_model() if client.configured else None
    hermes_status = HermesAdapter().status()
    return {
        "status": "ok",
        "app_version": app.version,
        "started_at": STARTED_AT,
        "openrouter_configured": client.configured,
        "default_model": settings.openrouter_model,
        "selected_model": selected_model,
        "database_backend": get_database_backend(),
        "database_path": str(settings.database_path),
        "policy_mode": settings.policy_mode,
        "local_restart_enabled": settings.enable_local_restart,
        "hermes_installed": hermes_status.installed,
        "hermes_configured": hermes_status.configured,
        "hermes_message": hermes_status.message,
    }


@app.get("/api/app/info")
def app_info() -> dict:
    updates_path = ROOT_DIR / "docs" / "updates.json"
    try:
        updates = json.loads(updates_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        updates = []

    static_files = {}
    for relative_path in ["static/index.html", "static/app.js", "static/styles.css", "app/main.py", "app/pipeline.py"]:
        path = ROOT_DIR / relative_path
        if path.exists():
            static_files[relative_path] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()

    return {
        "app_name": app.title,
        "app_version": app.version,
        "pid": os.getpid(),
        "started_at": STARTED_AT,
        "updates": updates,
        "file_timestamps": static_files,
    }


@app.post("/api/restart")
def restart_app(request: Request) -> dict:
    settings = get_settings()
    if not settings.enable_local_restart:
        raise HTTPException(status_code=403, detail="Local restart is disabled by configuration.")
    if not _is_local_request(request):
        raise HTTPException(status_code=403, detail="Restart is only allowed from localhost.")

    current_port = request.url.port or 8000
    restart_dir = DATA_DIR / "data"
    restart_dir.mkdir(exist_ok=True)
    restart_file = restart_dir / "restart_request.json"
    restart_file.write_text(
        json.dumps(
            {
                "request_id": str(uuid4()),
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "port": current_port,
                "pid": os.getpid(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "status": "restarting",
        "port": current_port,
        "url": str(request.base_url).rstrip("/"),
        "message": "Restart requested. The supervised backend will restart on the same port.",
    }


@app.get("/api/models")
def models() -> dict:
    client = OpenRouterClient()
    if not client.configured:
        return {"configured": False, "selected_model": None, "models": []}

    try:
        model_list = client.list_models()
        selected = client.select_model()
        return {
            "configured": True,
            "selected_model": selected,
            "selected_profile": profile_for_model(selected),
            "models": [
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "context_tokens": item.get("context_length"),
                    "pricing": item.get("pricing"),
                    "profile": profile_for_model(item.get("id"), item),
                }
                for item in model_list
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load OpenRouter models: {safe_error_message(exc)}") from exc


@app.get("/api/models/profile")
def model_profile(model: str = "auto") -> dict:
    client = OpenRouterClient()
    selected = client.select_model(model) if client.configured else model
    return profile_for_model(selected)


@app.get("/api/hermes/status")
def hermes_status() -> dict:
    status = HermesAdapter().status()
    return {
        "installed": status.installed,
        "configured": status.configured,
        "selected_model": status.selected_model,
        "message": status.message,
    }


@app.post("/api/settings/openrouter-key")
def set_openrouter_key(request_body: OpenRouterKeyRequest, request: Request) -> dict:
    """First-run setup: validate an OpenRouter API key against the API, persist it
    to .env, and activate it for the running process. Localhost-only."""
    if not _is_local_request(request):
        raise HTTPException(status_code=403, detail="Key setup is only allowed from localhost.")

    key = request_body.api_key.strip()
    if len(key) < 8:
        raise HTTPException(status_code=400, detail="That does not look like a valid API key.")

    # Validate against OpenRouter without touching global state. NOTE: the /models
    # endpoint is public (returns data even for a bogus key), so it cannot be
    # used to verify a key. A tiny authenticated completion does fail on a bad
    # key, so we only persist after that succeeds — never clobber a good key.
    test_client = OpenRouterClient(replace(get_settings(), openrouter_api_key=key))
    try:
        test_client.chat(
            messages=[{"role": "user", "content": "ping"}],
            temperature=0,
            max_tokens=1,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"OpenRouter did not accept that key: {safe_error_message(exc)}",
        ) from exc

    # Persist + activate.
    _save_env_var(DATA_DIR / ".env", "OPENROUTER_API_KEY", key)
    os.environ["OPENROUTER_API_KEY"] = key
    get_settings.cache_clear()

    selected = OpenRouterClient().select_model()
    return {"status": "saved", "configured": True, "selected_model": selected}


@app.post("/api/optimize", response_model=OptimizeResponse)
def optimize(request_body: OptimizeRequest) -> dict:
    try:
        user_id = request_body.user_id or "local-user"
        request_body.user_id = user_id

        # Resolve the conversation: attach to an existing chat, or start a new one.
        conversation_id = request_body.conversation_id
        if conversation_id and not repository.conversation_exists(conversation_id, user_id):
            conversation_id = None
        if conversation_id:
            # Follow-up turn: refine the previous winning prompt unless the
            # caller supplied an explicit base prompt.
            if not request_body.prior_prompt:
                request_body.prior_prompt = repository.get_last_winner_prompt(conversation_id, user_id)
        else:
            conversation_id = repository.create_conversation(user_id, _conversation_title(request_body.raw_prompt))
        request_body.conversation_id = conversation_id

        pipeline = PromptOptimizationPipeline(repository=repository)
        return pipeline.run(request_body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=safe_error_message(exc)) from exc


def _resolve_conversation(request_body: OptimizeRequest) -> str:
    """Attach the request to an existing chat or create a new one, mirroring the
    logic in /api/optimize. Returns the conversation id and mutates request_body
    in place (conversation_id, prior_prompt)."""
    user_id = request_body.user_id or "local-user"
    request_body.user_id = user_id
    conversation_id = request_body.conversation_id
    if conversation_id and not repository.conversation_exists(conversation_id, user_id):
        conversation_id = None
    if conversation_id:
        if not request_body.prior_prompt:
            request_body.prior_prompt = repository.get_last_winner_prompt(conversation_id, user_id)
    else:
        conversation_id = repository.create_conversation(user_id, _conversation_title(request_body.raw_prompt))
    request_body.conversation_id = conversation_id
    return conversation_id


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"


@app.post("/api/optimize/stream")
def optimize_stream(request_body: OptimizeRequest):
    """Same as /api/optimize, but streams Server-Sent Events so the UI can show
    live per-agent progress. Emits: a `conversation` event up front (so the chat
    can appear in the sidebar immediately), one `agent_start`/`agent_done` pair
    per pipeline agent, then a final `result` (or `error`) event."""
    conversation_id = _resolve_conversation(request_body)

    events: "queue.Queue" = queue.Queue()
    DONE = object()

    def progress(event: dict) -> None:
        events.put(event)

    def worker() -> None:
        try:
            pipeline = PromptOptimizationPipeline(repository=repository)
            result = pipeline.run(request_body, progress=progress)
            events.put({"type": "result", "data": result})
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as an error event
            events.put({"type": "error", "detail": safe_error_message(exc)})
        finally:
            events.put(DONE)

    threading.Thread(target=worker, daemon=True).start()

    def event_stream():
        # Hand the client the conversation id first so it can render the chat
        # (with a loading state) before any agent has finished.
        yield _sse({"type": "conversation", "conversation_id": conversation_id})
        while True:
            event = events.get()
            if event is DONE:
                break
            yield _sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get("/api/conversations")
def conversations(user_id: str = "local-user", limit: int = 50) -> list[dict]:
    return repository.list_conversations(user_id=user_id or "local-user", limit=max(1, min(200, limit)))


@app.get("/api/conversations/{conversation_id}")
def conversation_detail(conversation_id: str, user_id: str = "local-user") -> dict:
    conversation = repository.get_conversation(conversation_id=conversation_id, user_id=user_id or "local-user")
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user_id: str = "local-user") -> dict:
    deleted = repository.delete_conversation(conversation_id=conversation_id, user_id=user_id or "local-user")
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted", "conversation_id": conversation_id}


@app.post("/api/v1/optimize", response_model=OptimizeResponse)
def public_optimize(
    request_body: PublicOptimizeRequest,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    api_key = _require_api_key(authorization=authorization, x_api_key=x_api_key)
    optimize_request = OptimizeRequest(
        raw_prompt=request_body.raw_prompt,
        user_id=api_key["user_id"],
        target_model=request_body.target_model,
        versions=request_body.versions,
        force_clarification=request_body.force_clarification,
        use_hermes=bool(request_body.use_hermes),
    )
    try:
        pipeline = PromptOptimizationPipeline(repository=repository)
        return pipeline.run(optimize_request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=safe_error_message(exc)) from exc


@app.get("/api/history")
def history(user_id: str = "local-user", limit: int = 20) -> list[dict]:
    return repository.list_history(user_id=user_id or "local-user", limit=max(1, min(100, limit)))


@app.get("/api/runs/{history_id}")
def run_detail(history_id: str, user_id: str = "local-user") -> dict:
    run = repository.get_run(history_id=history_id, user_id=user_id or "local-user")
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.post("/api/feedback")
def feedback(request_body: FeedbackRequest) -> dict:
    feedback_id = repository.save_feedback(
        user_id=request_body.user_id or "local-user",
        version_id=request_body.version_id,
        rating=request_body.rating,
        comment=request_body.comment,
        outcome=request_body.outcome,
    )
    return {"feedback_id": feedback_id, "status": "saved"}


@app.get("/api/feedback/summary")
def feedback_summary(user_id: str = "local-user") -> dict:
    return repository.get_feedback_summary(user_id=user_id or "local-user")


@app.get("/api/memory/insights")
def memory_insights(user_id: str = "local-user") -> dict:
    return repository.get_memory_insights(user_id=user_id or "local-user")


@app.get("/api/api-keys")
def api_keys(user_id: str = "local-user") -> list[dict]:
    return repository.list_api_keys(user_id=user_id or "local-user")


@app.post("/api/api-keys")
def create_api_key(request_body: ApiKeyCreateRequest) -> dict:
    try:
        return repository.create_api_key(
            user_id=request_body.user_id or "local-user",
            name=request_body.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=safe_error_message(exc)) from exc


@app.post("/api/api-keys/{key_id}/revoke")
def revoke_api_key(key_id: str, user_id: str = "local-user") -> dict:
    revoked = repository.revoke_api_key(user_id=user_id or "local-user", key_id=key_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"status": "revoked", "key_id": key_id}


@app.post("/api/api-keys/verify")
def verify_api_key(request_body: ApiKeyVerifyRequest) -> dict:
    verified = repository.verify_api_key(request_body.api_key)
    if verified is None:
        return {"valid": False}
    return {"valid": True, "api_key": verified}


def _save_env_var(path, name: str, value: str) -> None:
    """Update or append NAME=value in a .env file, preserving other lines."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    found = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(f"{name}=") or stripped.startswith(f"{name} ="):
            out.append(f"{name}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{name}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _conversation_title(raw_prompt: str) -> str:
    return derive_title(raw_prompt, empty_default="New prompt")


def _is_local_request(request: Request) -> bool:
    allowed_hosts = {"127.0.0.1", "::1", "localhost"}
    client_host = request.client.host if request.client else ""
    host_header = request.headers.get("host", "")
    if host_header.startswith("["):
        request_host = host_header.split("]", 1)[0].strip("[]")
    else:
        request_host = host_header.split(":", 1)[0]
    return client_host in allowed_hosts and request_host in allowed_hosts


def _api_key_from_headers(authorization: str | None = None, x_api_key: str | None = None) -> str | None:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    authorization = authorization or ""
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def _require_api_key(authorization: str | None = None, x_api_key: str | None = None) -> dict:
    api_key = _api_key_from_headers(authorization=authorization, x_api_key=x_api_key)
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")
    verified = repository.verify_api_key(api_key)
    if verified is None:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    return verified


app.mount("/", StaticFiles(directory=ROOT_DIR / "static", html=True), name="static")
