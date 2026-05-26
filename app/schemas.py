from typing import Any

from pydantic import BaseModel, Field


class OptimizeRequest(BaseModel):
    raw_prompt: str = Field(..., min_length=3)
    user_id: str = "local-user"
    target_model: str | None = None
    versions: int = Field(default=3, ge=1, le=5)
    force_clarification: bool = False
    use_hermes: bool = True
    conversation_id: str | None = None
    prior_prompt: str | None = None


class PublicOptimizeRequest(BaseModel):
    raw_prompt: str = Field(..., min_length=3)
    target_model: str | None = None
    versions: int = Field(default=3, ge=1, le=5)
    force_clarification: bool = False
    use_hermes: bool = True


class FeedbackRequest(BaseModel):
    version_id: str
    user_id: str = "local-user"
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None
    outcome: str | None = None


class ApiKeyCreateRequest(BaseModel):
    user_id: str = "local-user"
    name: str = Field(..., min_length=2, max_length=80)


class ApiKeyVerifyRequest(BaseModel):
    api_key: str = Field(..., min_length=12)


class OpenRouterKeyRequest(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=200)


class OptimizeResponse(BaseModel):
    history_id: str
    conversation_id: str | None = None
    is_refinement: bool = False
    model_used: str | None = None
    needs_clarification: bool
    clarification_questions: list[str]
    assumptions: list[str]
    final_prompt: str
    winner_label: str
    winner_version_id: str | None
    score: int
    versions: list[dict[str, Any]]
    scores: list[dict[str, Any]]
    critiques: list[dict[str, Any]]
    stress_tests: list[dict[str, Any]]
    comparison: dict[str, Any]
    run_trace: list[dict[str, Any]]
    intent: dict[str, Any]
    context: dict[str, Any]
    hermes_plan: dict[str, Any] | None = None
    model_profile: dict[str, Any] | None = None
    memory_matches: list[dict[str, Any]]
