"""Supabase-backed aiogram 3 FSM storage — persists state across bot restarts."""
from __future__ import annotations

from typing import Any, Dict, Optional

from aiogram.fsm.storage.base import BaseStorage, StorageKey


class SupabaseStorage(BaseStorage):
    """FSM storage backed by the fsm_storage table in Supabase."""

    def _k(self, key: StorageKey) -> dict:
        return {
            "bot_id": key.bot_id,
            "chat_id": key.chat_id,
            "user_id": key.user_id,
            "destiny": key.destiny,
        }

    async def set_state(
        self, key: StorageKey, state: Optional[str] = None
    ) -> None:
        from database.models import get_client
        sb = get_client()
        k = self._k(key)
        state_val = str(state) if state is not None else None
        resp = await sb.table("fsm_storage").update({"state": state_val}).match(k).execute()
        if not resp.data:
            await sb.table("fsm_storage").insert({**k, "state": state_val, "data": {}}).execute()

    async def get_state(self, key: StorageKey) -> Optional[str]:
        from database.models import get_client
        sb = get_client()
        resp = await sb.table("fsm_storage").select("state").match(self._k(key)).execute()
        if not resp.data:
            return None
        return resp.data[0].get("state")

    async def set_data(
        self, key: StorageKey, data: Dict[str, Any]
    ) -> None:
        from database.models import get_client
        sb = get_client()
        k = self._k(key)
        resp = await sb.table("fsm_storage").update({"data": data}).match(k).execute()
        if not resp.data:
            await sb.table("fsm_storage").insert({**k, "state": None, "data": data}).execute()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        from database.models import get_client
        sb = get_client()
        resp = await sb.table("fsm_storage").select("data").match(self._k(key)).execute()
        if not resp.data:
            return {}
        d = resp.data[0].get("data")
        return d if isinstance(d, dict) else {}

    async def close(self) -> None:
        pass
