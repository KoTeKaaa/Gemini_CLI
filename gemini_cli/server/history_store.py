"""User-scoped durable event storage. SQL RPCs keep batches atomic under RLS."""
from uuid import UUID, uuid5, NAMESPACE_URL
from ..runtime.history import persistent_tool_message


class HistoryStore:
    def __init__(self, db, user_id):
        self.db, self.user_id = db, user_id

    def metadata(self, chat_id):
        rows = self.db.table("chats").select("*").eq("id", chat_id).eq("user_id", self.user_id).execute().data
        if not rows:
            raise LookupError("Чат не найден")
        return rows[0]

    def read(self, chat_id):
        self.metadata(chat_id)
        rows, offset = [], 0
        while True:
            page = self.db.table("messages").select("*").eq("chat_id", chat_id).order(
                "sequence").range(offset, offset + 499).execute().data
            if not page:
                return rows
            rows.extend(page)
            offset += len(page)

    def append(self, chat_id, rows, *, turn_id=None, request_id=None, start=0, status="running"):
        self.metadata(chat_id)
        events = []
        for index, source in enumerate(rows, start):
            content, args = persistent_tool_message(source["role"], source.get("name"),
                                                    source.get("content", ""), source.get("args"))
            event = {key: source.get(key) for key in ("role", "name", "call_id", "thought_signature")}
            event.update(content=content, args=args, status=status)
            if request_id is not None:
                event.update(id=str(uuid5(NAMESPACE_URL, f"gemini:{request_id}:{index}")),
                             request_id=str(UUID(str(request_id))), turn_id=str(UUID(str(turn_id))),
                             event_index=index)
            events.append(event)
        if events:
            self.db.rpc("append_history_events", {"target_chat": chat_id, "events": events}).execute()
        return start + len(events)

    def finish(self, chat_id, request_id, status):
        if request_id is not None:
            self.db.rpc("update_history_request_status", {"target_chat": chat_id,
                "request_uuid": str(request_id), "new_status": status}).execute()

    def set_summary(self, chat_id, summary, boundary_id):
        self.metadata(chat_id)
        self.db.rpc("set_history_summary", {"target_chat": chat_id, "summary_text": summary,
                    "boundary_id": boundary_id}).execute()

    def fork(self, chat_id, title, boundary_id=None):
        self.metadata(chat_id)
        data = self.db.rpc("fork_history_chat", {"target_chat": chat_id, "new_title": title,
                    "boundary_id": boundary_id}).execute().data
        return data[0] if isinstance(data, list) else data
