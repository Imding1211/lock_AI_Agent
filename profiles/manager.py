import asyncio
import os
import re
from pathlib import Path
from psycopg import AsyncConnection


# ── Module-level facts DB connection (global conn pattern) ──
_facts_conn: AsyncConnection | None = None


async def init_facts_db(config: dict):
    """Initialize the facts DB connection from config."""
    global _facts_conn
    uri_env = config.get("facts_postgres_uri_env", "POSTGRES_URI")
    uri = os.getenv(uri_env)
    if not uri:
        print(f"[Facts DB] 警告：環境變數 {uri_env} 未設定，facts 功能降級為停用")
        return
    try:
        _facts_conn = await AsyncConnection.connect(uri)
        print("[Facts DB] 已連線至 PostgreSQL（user_facts）")
    except Exception as e:
        print(f"[Facts DB] 連線失敗，降級為停用: {e}")
        _facts_conn = None


async def close_facts_db():
    """Close the facts DB connection."""
    global _facts_conn
    if _facts_conn is not None:
        await _facts_conn.close()
        _facts_conn = None


class ProfileManager:
    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.base_dir = Path(config.get("profile_dir", "./data/profiles"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.facts_enabled = config.get("facts_enabled", False)
        self.fact_attributes = config.get("fact_attributes", [])

    def _get_profile_path(self, user_id: str) -> Path:
        safe_name = re.sub(r'[^\w\-]', '_', user_id)
        return self.base_dir / f"{safe_name}.md"

    async def load_profile(self, user_id: str) -> str:
        if not self.enabled:
            return ""
        path = self._get_profile_path(user_id)

        def _read():
            if path.exists():
                return path.read_text(encoding="utf-8")
            return ""

        return await asyncio.to_thread(_read)

    async def save_profile(self, user_id: str, content: str) -> None:
        if not self.enabled:
            return
        path = self._get_profile_path(user_id)

        def _write():
            path.write_text(content, encoding="utf-8")

        await asyncio.to_thread(_write)

    async def load_facts(self, user_id: str) -> dict:
        """Load current facts from user_facts table."""
        if not self.facts_enabled or _facts_conn is None:
            return {}
        try:
            cursor = await _facts_conn.execute(
                "SELECT attr_key, attr_val FROM user_facts WHERE user_id = %s AND is_current = TRUE",
                (user_id,),
            )
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            print(f"[Facts DB] load_facts 失敗: {e}")
            return {}

    async def update_fact(self, user_id: str, attr_key: str, attr_val: str):
        """SCD Type 2 upsert: expire old value (if different), insert new."""
        if not self.facts_enabled or _facts_conn is None:
            return
        try:
            # 1. Expire old row if value changed
            await _facts_conn.execute(
                "UPDATE user_facts SET is_current = FALSE, end_date = NOW() "
                "WHERE user_id = %s AND attr_key = %s AND is_current = TRUE AND attr_val != %s",
                (user_id, attr_key, attr_val),
            )
            # 2. Insert only if no current row with same value exists
            await _facts_conn.execute(
                "INSERT INTO user_facts (user_id, attr_key, attr_val, is_current, start_date) "
                "SELECT %s, %s, %s, TRUE, NOW() "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM user_facts WHERE user_id = %s AND attr_key = %s AND attr_val = %s AND is_current = TRUE"
                ")",
                (user_id, attr_key, attr_val, user_id, attr_key, attr_val),
            )
            await _facts_conn.commit()
        except Exception as e:
            print(f"[Facts DB] update_fact 失敗 ({attr_key}={attr_val}): {e}")

    def format_facts(self, facts: dict) -> str:
        """Format facts dict as [Verified Fact] lines."""
        if not facts:
            return ""
        lines = [f"[Verified Fact] {k}: {v}" for k, v in facts.items()]
        return "\n".join(lines)

    async def load_full_profile(self, user_id: str) -> str:
        """Load facts + .md profile combined. Facts section first (higher priority)."""
        facts = await self.load_facts(user_id)
        facts_text = self.format_facts(facts)
        md_text = await self.load_profile(user_id)

        parts = [p for p in [facts_text, md_text] if p]
        return "\n\n".join(parts)
