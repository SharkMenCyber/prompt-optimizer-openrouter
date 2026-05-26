from app.db.repository import PromptRepository


class MemoryAgent:
    def __init__(self, repository: PromptRepository):
        self.repository = repository

    def retrieve_patterns(self, user_id: str, task_type: str, raw_prompt: str, limit: int = 3) -> list[dict]:
        return self.repository.find_successful_patterns(
            user_id=user_id,
            task_type=task_type,
            raw_prompt=raw_prompt,
            limit=limit,
        )
