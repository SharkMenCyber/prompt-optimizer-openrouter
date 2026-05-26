import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.db.database import get_connection
from app.security import (
    create_local_api_key,
    hash_secret,
    redact_text,
    redact_value,
    verify_secret,
    visible_key_prefix,
)


def _id() -> str:
    return str(uuid4())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PromptRepository:
    def ensure_user(self, user_id: str) -> None:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO users (id)
                VALUES (?)
                """,
                (user_id,),
            )

    def save_optimization_run(
        self,
        user_id: str,
        raw_prompt: str,
        intent: dict[str, Any],
        target_model: str | None,
        versions: list[dict[str, Any]],
        scores: list[dict[str, Any]],
        agent_outputs: list[dict[str, Any]],
        winner_label: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_user(user_id)
        history_id = _id()
        safe_raw_prompt = redact_text(raw_prompt) or ""
        safe_intent = redact_value(intent)
        score_by_label = {score.get("label"): redact_value(score) for score in scores}
        version_ids: dict[str, str] = {}

        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO prompt_history (id, user_id, raw_prompt, intent_json, task_type, target_model, conversation_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    history_id,
                    user_id,
                    safe_raw_prompt,
                    json.dumps(safe_intent),
                    safe_intent.get("task_type"),
                    target_model,
                    conversation_id,
                ),
            )
            if conversation_id:
                connection.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (_utc_now(), conversation_id),
                )

            for version in versions:
                version_id = _id()
                label = version.get("label") or f"v{len(version_ids) + 1}"
                version_ids[label] = version_id
                prompt_text = redact_text(version.get("prompt_text") or "") or ""
                score = score_by_label.get(label) or {}
                connection.execute(
                    """
                    INSERT INTO prompt_versions (
                        id, history_id, label, strategy, version_text, model, is_winner
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        history_id,
                        label,
                        version.get("strategy"),
                        prompt_text,
                        target_model,
                        1 if label == winner_label else 0,
                    ),
                )
                if score:
                    criteria = score.get("criteria") or {}
                    connection.execute(
                        """
                        INSERT INTO prompt_scores (
                            id, version_id, clarity, specificity, completeness, context_strength,
                            constraint_quality, output_control, safety, usefulness, total, score_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            _id(),
                            version_id,
                            criteria.get("clarity"),
                            criteria.get("specificity"),
                            criteria.get("completeness"),
                            criteria.get("context_strength"),
                            criteria.get("constraint_quality"),
                            criteria.get("output_control"),
                            criteria.get("safety"),
                            criteria.get("usefulness"),
                            score.get("total"),
                            json.dumps(score),
                        ),
                    )

            for item in agent_outputs:
                connection.execute(
                    """
                    INSERT INTO agent_outputs (id, history_id, agent_name, output_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        _id(),
                        history_id,
                        item.get("agent_name") or "agent",
                        json.dumps(redact_value(item.get("output"))),
                    ),
                )

        return {"history_id": history_id, "version_ids": version_ids}

    # ------------------------------------------------------------------
    # Conversations (multi-turn chats)
    # ------------------------------------------------------------------
    def create_conversation(self, user_id: str, title: str) -> str:
        self.ensure_user(user_id)
        conversation_id = _id()
        safe_title = (redact_text(title) or "").strip() or "New prompt"
        safe_title = safe_title[:120]
        now = _utc_now()
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO conversations (id, user_id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, user_id, safe_title, now, now),
            )
        return conversation_id

    def conversation_exists(self, conversation_id: str, user_id: str) -> bool:
        with get_connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
        return row is not None

    def touch_conversation(self, conversation_id: str) -> None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_utc_now(), conversation_id),
            )

    def rename_conversation(self, conversation_id: str, user_id: str, title: str) -> bool:
        safe_title = (redact_text(title) or "").strip()[:120]
        if not safe_title:
            return False
        with get_connection() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET title = ? WHERE id = ? AND user_id = ?",
                (safe_title, conversation_id, user_id),
            )
        return cursor.rowcount > 0

    def delete_conversation(self, conversation_id: str, user_id: str) -> bool:
        """Delete a conversation and everything beneath it: its prompt history,
        every version, the scores and feedback on those versions, and the agent
        outputs. The schema has no ON DELETE CASCADE (and SQLite skips FK
        enforcement by default), so we sweep the child rows ourselves inside the
        one transaction get_connection() provides. Returns False if the chat
        does not exist or is not owned by this user."""
        with get_connection() as connection:
            owned = connection.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
            if owned is None:
                return False

            history_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM prompt_history WHERE conversation_id = ? AND user_id = ?",
                    (conversation_id, user_id),
                ).fetchall()
            ]
            if history_ids:
                history_marks = ",".join("?" for _ in history_ids)
                version_ids = [
                    row["id"]
                    for row in connection.execute(
                        f"SELECT id FROM prompt_versions WHERE history_id IN ({history_marks})",
                        history_ids,
                    ).fetchall()
                ]
                if version_ids:
                    version_marks = ",".join("?" for _ in version_ids)
                    connection.execute(
                        f"DELETE FROM feedback WHERE version_id IN ({version_marks})",
                        version_ids,
                    )
                    connection.execute(
                        f"DELETE FROM prompt_scores WHERE version_id IN ({version_marks})",
                        version_ids,
                    )
                connection.execute(
                    f"DELETE FROM prompt_versions WHERE history_id IN ({history_marks})",
                    history_ids,
                )
                connection.execute(
                    f"DELETE FROM agent_outputs WHERE history_id IN ({history_marks})",
                    history_ids,
                )
                connection.execute(
                    f"DELETE FROM prompt_history WHERE id IN ({history_marks})",
                    history_ids,
                )
            connection.execute(
                "DELETE FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            )
        return True

    def list_conversations(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        self.ensure_user(user_id)
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at,
                       COUNT(ph.id) AS turn_count,
                       MAX(ph.created_at) AS last_turn_at
                FROM conversations c
                LEFT JOIN prompt_history ph ON ph.conversation_id = c.id
                WHERE c.user_id = ?
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                LIMIT ?
                """,
                (user_id, max(1, min(200, limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_last_winner_prompt(self, conversation_id: str, user_id: str) -> str | None:
        """Return the winning prompt text from the most recent turn in a
        conversation, used as the base for a refinement follow-up."""
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT pv.version_text
                FROM prompt_history ph
                JOIN prompt_versions pv ON pv.history_id = ph.id AND pv.is_winner = 1
                WHERE ph.conversation_id = ? AND ph.user_id = ?
                ORDER BY ph.created_at DESC
                LIMIT 1
                """,
                (conversation_id, user_id),
            ).fetchone()
        return row["version_text"] if row else None

    def get_conversation(self, conversation_id: str, user_id: str) -> dict[str, Any] | None:
        """Return a conversation with its ordered turns. Each turn carries the
        user's prompt and the winning optimized result for chat rendering."""
        with get_connection() as connection:
            conversation_row = connection.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
            if conversation_row is None:
                return None

            turn_rows = connection.execute(
                """
                SELECT ph.id AS history_id, ph.raw_prompt, ph.task_type, ph.target_model, ph.created_at,
                       pv.id AS winner_version_id, pv.label AS winner_label,
                       pv.version_text AS winner_prompt, ps.total AS winner_score
                FROM prompt_history ph
                LEFT JOIN prompt_versions pv ON pv.history_id = ph.id AND pv.is_winner = 1
                LEFT JOIN prompt_scores ps ON ps.version_id = pv.id
                WHERE ph.conversation_id = ? AND ph.user_id = ?
                ORDER BY ph.created_at ASC
                """,
                (conversation_id, user_id),
            ).fetchall()

        return {
            "conversation": dict(conversation_row),
            "turns": [dict(row) for row in turn_rows],
        }

    def list_history(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        self.ensure_user(user_id)
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT ph.id, ph.raw_prompt, ph.task_type, ph.target_model, ph.created_at,
                       pv.id AS winner_version_id, pv.label AS winner_label,
                       ps.total AS winner_score
                FROM prompt_history ph
                LEFT JOIN prompt_versions pv ON pv.history_id = ph.id AND pv.is_winner = 1
                LEFT JOIN prompt_scores ps ON ps.version_id = pv.id
                WHERE ph.user_id = ?
                ORDER BY ph.created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, history_id: str, user_id: str = "local-user") -> dict[str, Any] | None:
        self.ensure_user(user_id)
        with get_connection() as connection:
            history_row = connection.execute(
                """
                SELECT id, user_id, raw_prompt, intent_json, task_type, target_model, created_at
                FROM prompt_history
                WHERE id = ? AND user_id = ?
                """,
                (history_id, user_id),
            ).fetchone()
            if history_row is None:
                return None

            version_rows = connection.execute(
                """
                SELECT pv.id, pv.label, pv.strategy, pv.version_text, pv.model, pv.is_winner, pv.created_at,
                       ps.total AS score_total, ps.score_json
                FROM prompt_versions pv
                LEFT JOIN prompt_scores ps ON ps.version_id = pv.id
                WHERE pv.history_id = ?
                ORDER BY pv.created_at ASC
                """,
                (history_id,),
            ).fetchall()

            agent_rows = connection.execute(
                """
                SELECT agent_name, output_json, created_at
                FROM agent_outputs
                WHERE history_id = ?
                ORDER BY created_at ASC
                """,
                (history_id,),
            ).fetchall()

            feedback_rows = connection.execute(
                """
                SELECT f.id, f.version_id, f.rating, f.comment, f.outcome, f.created_at
                FROM feedback f
                JOIN prompt_versions pv ON pv.id = f.version_id
                WHERE pv.history_id = ? AND f.user_id = ?
                ORDER BY f.created_at DESC
                """,
                (history_id, user_id),
            ).fetchall()

        history = dict(history_row)
        history["intent"] = json.loads(history.pop("intent_json") or "{}")

        versions = []
        for row in version_rows:
            version = dict(row)
            score_json = version.pop("score_json")
            version["prompt_text"] = version.pop("version_text")
            version["is_winner"] = bool(version["is_winner"])
            version["score"] = json.loads(score_json) if score_json else None
            versions.append(version)

        agent_outputs = []
        for row in agent_rows:
            output = dict(row)
            output["output"] = json.loads(output.pop("output_json") or "{}")
            agent_outputs.append(output)

        winner = next((version for version in versions if version["is_winner"]), versions[0] if versions else None)
        return {
            "history": history,
            "versions": versions,
            "agent_outputs": agent_outputs,
            "feedback": [dict(row) for row in feedback_rows],
            "winner": winner,
        }

    def save_feedback(
        self,
        user_id: str,
        version_id: str,
        rating: int,
        comment: str | None,
        outcome: str | None,
    ) -> str:
        self.ensure_user(user_id)
        feedback_id = _id()
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO feedback (id, version_id, user_id, rating, comment, outcome)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback_id,
                    version_id,
                    user_id,
                    rating,
                    redact_text(comment),
                    redact_text(outcome),
                ),
            )
        return feedback_id

    def get_feedback_summary(self, user_id: str = "local-user") -> dict[str, Any]:
        self.ensure_user(user_id)
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total_feedback,
                       AVG(rating) AS average_rating,
                       SUM(CASE WHEN rating >= 4 THEN 1 ELSE 0 END) AS positive_count,
                       SUM(CASE WHEN rating <= 2 THEN 1 ELSE 0 END) AS negative_count
                FROM feedback
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
        result = dict(row)
        result["average_rating"] = round(result["average_rating"], 2) if result["average_rating"] else None
        return result

    def find_successful_patterns(
        self,
        user_id: str,
        task_type: str,
        raw_prompt: str = "",
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        self.ensure_user(user_id)
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT pv.label, pv.strategy, pv.version_text, ps.total, ph.task_type,
                       ph.raw_prompt, COALESCE(AVG(f.rating), 0) AS average_feedback,
                       COUNT(f.id) AS feedback_count
                FROM prompt_versions pv
                JOIN prompt_history ph ON ph.id = pv.history_id
                JOIN prompt_scores ps ON ps.version_id = pv.id
                LEFT JOIN feedback f ON f.version_id = pv.id
                WHERE ph.user_id = ?
                  AND (ph.task_type = ? OR ps.total >= 88 OR f.rating >= 4)
                  AND (ps.total >= 80 OR f.rating >= 4)
                GROUP BY pv.id
                ORDER BY ps.total DESC, pv.created_at DESC
                LIMIT 25
                """,
                (user_id, task_type),
            ).fetchall()

        prompt_tokens = self._tokens(raw_prompt)
        ranked = []
        for row in rows:
            item = dict(row)
            if self._is_risky_memory(item.get("raw_prompt", "")) or self._is_risky_memory(item.get("version_text", "")):
                continue
            candidate_tokens = self._tokens(item.get("raw_prompt", "") + " " + item.get("version_text", ""))
            overlap = len(prompt_tokens & candidate_tokens)
            task_bonus = 8 if item.get("task_type") == task_type else 0
            feedback_bonus = float(item.get("average_feedback") or 0) * 3
            score_bonus = float(item.get("total") or 0) / 10
            relevance = task_bonus + feedback_bonus + score_bonus + overlap
            item["memory_relevance"] = round(relevance, 2)
            item["match_reason"] = self._memory_reason(item, overlap, task_type)
            ranked.append(item)

        ranked.sort(key=lambda item: item["memory_relevance"], reverse=True)
        return ranked[:limit]

    def get_memory_insights(self, user_id: str = "local-user") -> dict[str, Any]:
        self.ensure_user(user_id)
        with get_connection() as connection:
            task_rows = connection.execute(
                """
                SELECT ph.task_type, COUNT(*) AS runs, AVG(ps.total) AS average_score
                FROM prompt_history ph
                JOIN prompt_versions pv ON pv.history_id = ph.id AND pv.is_winner = 1
                LEFT JOIN prompt_scores ps ON ps.version_id = pv.id
                WHERE ph.user_id = ?
                GROUP BY ph.task_type
                ORDER BY runs DESC, average_score DESC
                """,
                (user_id,),
            ).fetchall()
            best_rows = connection.execute(
                """
                SELECT ph.task_type, pv.label, pv.strategy, ps.total, ph.raw_prompt
                FROM prompt_history ph
                JOIN prompt_versions pv ON pv.history_id = ph.id AND pv.is_winner = 1
                LEFT JOIN prompt_scores ps ON ps.version_id = pv.id
                WHERE ph.user_id = ?
                ORDER BY ps.total DESC, ph.created_at DESC
                LIMIT 5
                """,
                (user_id,),
            ).fetchall()
        return {
            "task_types": [
                {
                    "task_type": row["task_type"] or "general",
                    "runs": row["runs"],
                    "average_score": round(row["average_score"], 2) if row["average_score"] else None,
                }
                for row in task_rows
            ],
            "best_prompts": [dict(row) for row in best_rows],
        }

    def list_api_keys(self, user_id: str = "local-user") -> list[dict[str, Any]]:
        self.ensure_user(user_id)
        with get_connection() as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, name, key_prefix, revoked, created_at, last_used_at
                FROM api_keys
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [{**dict(row), "revoked": bool(row["revoked"])} for row in rows]

    def create_api_key(self, user_id: str, name: str) -> dict[str, Any]:
        self.ensure_user(user_id)
        safe_name = (redact_text(name) or "").strip()
        if len(safe_name) < 2:
            raise ValueError("API key name must be at least 2 characters.")

        api_key, key_prefix, key_hash = create_local_api_key()
        key_id = _id()
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO api_keys (id, user_id, name, key_prefix, key_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key_id, user_id, safe_name[:80], key_prefix, key_hash),
            )
        return {
            "id": key_id,
            "user_id": user_id,
            "name": safe_name[:80],
            "key_prefix": key_prefix,
            "api_key": api_key,
            "revoked": False,
            "created_at": None,
            "last_used_at": None,
            "one_time_display": True,
        }

    def revoke_api_key(self, user_id: str, key_id: str) -> bool:
        self.ensure_user(user_id)
        with get_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE api_keys
                SET revoked = 1
                WHERE id = ? AND user_id = ?
                """,
                (key_id, user_id),
            )
        return cursor.rowcount > 0

    def verify_api_key(self, api_key: str) -> dict[str, Any] | None:
        key_hash = hash_secret(api_key)
        with get_connection() as connection:
            row = connection.execute(
                """
                SELECT id, user_id, name, key_prefix, key_hash, revoked, created_at, last_used_at
                FROM api_keys
                WHERE key_hash = ? AND revoked = 0
                LIMIT 1
                """,
                (key_hash,),
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            if not verify_secret(api_key, item.pop("key_hash")):
                return None
            connection.execute(
                "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                (_utc_now(), item["id"]),
            )

        item["revoked"] = bool(item["revoked"])
        item["provided_key_prefix"] = visible_key_prefix(api_key)
        return item

    def redact_stored_sensitive_data(self) -> dict[str, int]:
        text_columns = {
            "prompt_history": ["raw_prompt", "intent_json"],
            "prompt_versions": ["version_text"],
            "prompt_scores": ["score_json"],
            "feedback": ["comment", "outcome"],
            "agent_outputs": ["output_json"],
        }
        updated_rows = 0
        updated_values = 0

        with get_connection() as connection:
            for table, columns in text_columns.items():
                existing = self._table_columns(connection, table)
                if not existing:
                    continue
                safe_columns = [column for column in columns if column in existing]
                if not safe_columns:
                    continue
                rows = connection.execute(
                    f"SELECT id, {', '.join(safe_columns)} FROM {table}"
                ).fetchall()
                for row in rows:
                    updates: dict[str, str | None] = {}
                    for column in safe_columns:
                        value = row[column]
                        safe_value = redact_text(value)
                        if safe_value != value:
                            updates[column] = safe_value
                    if not updates:
                        continue
                    set_clause = ", ".join(f"{column} = ?" for column in updates)
                    connection.execute(
                        f"UPDATE {table} SET {set_clause} WHERE id = ?",
                        (*updates.values(), row["id"]),
                    )
                    updated_rows += 1
                    updated_values += len(updates)

        return {"updated_rows": updated_rows, "updated_values": updated_values}

    def _table_columns(self, connection, table: str) -> set[str]:
        try:
            return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            return set()

    def _tokens(self, text: str) -> set[str]:
        stop_words = {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "you",
            "are",
            "make",
            "create",
            "prompt",
            "write",
            "help",
            "from",
            "into",
        }
        return {
            token
            for token in re.findall(r"[a-z0-9]{3,}", text.lower())
            if token not in stop_words
        }

    def _memory_reason(self, item: dict[str, Any], overlap: int, task_type: str) -> str:
        reasons = []
        if item.get("task_type") == task_type:
            reasons.append(f"same task type: {task_type}")
        if item.get("total"):
            reasons.append(f"score {item['total']}/100")
        if item.get("average_feedback"):
            reasons.append(f"feedback {round(float(item['average_feedback']), 2)}/5")
        if overlap:
            reasons.append(f"{overlap} keyword matches")
        return "; ".join(reasons) or "high-scoring prior prompt"

    def _is_risky_memory(self, text: str) -> bool:
        """Keep genuinely abusive prompts out of memory reuse, but do NOT flag
        bare security nouns ("password", "api key", "credential"). Those appear
        constantly in legitimate defensive prompts (secure storage, password
        managers, secret redaction); flagging them blocked good prompts from
        ever being reused."""
        lowered = text.lower()
        # Unambiguous abuse — risky on their own.
        always_risky = [
            "jailbreak",
            "phishing",
            "malware",
            "ransomware",
            "spyware",
            "keylogger",
            "trojan",
            "backdoor",
            "botnet",
            "exfiltrate",
        ]
        if any(term in lowered for term in always_risky):
            return True
        # Known attack phrases.
        risky_phrases = [
            "steal password",
            "steal token",
            "steal login",
            "steal credential",
            "bypass security",
            "evade detection",
            "disable antivirus",
            "unauthorized access",
            "cookie theft",
        ]
        if any(phrase in lowered for phrase in risky_phrases):
            return True
        # An attack verb next to a sensitive noun catches combinations not
        # spelled out above; a sensitive noun on its own stays allowed.
        attack_verbs = ["steal", "hack", "crack", "dump", "harvest", "hijack"]
        sensitive_nouns = ["password", "api key", "secret key", "credential", "session token", "login"]
        return any(verb in lowered for verb in attack_verbs) and any(noun in lowered for noun in sensitive_nouns)
