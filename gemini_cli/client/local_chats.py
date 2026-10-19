"""Приватная SQLite на профиль; временное хранилище существует только в RAM."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
from uuid import uuid4

from ..runtime.history import persistent_tool_message


class LocalChats:
    def __init__(self, root: Path, profile="default", *, temporary=False):
        self.lock = RLock()
        self.memory = sqlite3.connect(":memory:", check_same_thread=False) if temporary else None
        self.path = None
        if not temporary:
            directory = root / "local" / hashlib.sha256(profile.encode()).hexdigest()
            for folder in (root, root / "local", directory):
                folder.mkdir(mode=0o700, parents=True, exist_ok=True)
                if os.name == "posix":
                    folder.chmod(0o700)
            self.path = directory / "chats.sqlite3"
            if self.path.is_symlink():
                raise ValueError("Локальная БД не должна быть ссылкой")
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(descriptor)
            if os.name == "posix":
                self.path.chmod(0o600)
        with self.connection() as db:
            # Serialize the schema check with other instances opening this profile.
            db.execute("begin immediate")
            version = db.execute("pragma user_version").fetchone()[0]
            if version > 2:
                raise ValueError("Локальная БД создана более новой версией приложения")
            if version < 2:
                # Explicit BEGIN keeps DDL, backfill and version bump atomic.
                db.execute("""create table if not exists chats (
                    id text primary key, title text not null, created_at text not null)""")
                db.execute("""create table if not exists messages (
                    sequence integer primary key autoincrement,
                    chat_id text not null references chats(id) on delete cascade,
                    role text not null check (role in ('user','model','tool')),
                    content text not null, name text, args text, call_id text, thought_signature text)""")
                for column in ("summary", "summary_boundary", "fork_parent_id", "fork_boundary"):
                    db.execute(f"alter table chats add column {column} text")
                for definition in ("id text", "turn_id text", "request_id text", "event_index integer",
                                   "status text not null default 'legacy'"):
                    db.execute(f"alter table messages add column {definition}")
                for row in db.execute("select sequence from messages").fetchall():
                    db.execute("update messages set id=?, event_index=sequence where sequence=?",
                               (str(uuid4()), row["sequence"]))
                db.execute("create unique index messages_id on messages(id)")
                db.execute("create unique index messages_event on messages(chat_id,request_id,event_index)")
                db.execute("""create table generation_requests (
                    request_id text primary key not null,
                    chat_id text not null references chats(id) on delete cascade,
                    turn_id text not null, status text not null default 'running')""")
                db.execute("pragma user_version=2")

    @contextmanager
    def connection(self):
        with self.lock:
            db = self.memory or sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            db.execute("pragma foreign_keys=on")
            try:
                with db:
                    yield db
            finally:
                if self.memory is None:
                    db.close()

    def create(self, title: str) -> dict:
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("Некорректное название чата")
        row = {"id": str(uuid4()), "title": title.strip(), "created_at": datetime.now(timezone.utc).isoformat()}
        with self.connection() as db:
            db.execute("insert into chats(id,title,created_at) values (:id,:title,:created_at)", row)
        return row

    def list(self) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute("select * from chats order by created_at desc")]

    def read(self, chat_id: str) -> list[dict]:
        with self.connection() as db:
            if not db.execute("select 1 from chats where id=?", (chat_id,)).fetchone():
                raise LookupError("Чат не найден в локальном профиле")
            rows = db.execute("select * from messages where chat_id=? order by sequence", (chat_id,)).fetchall()
        return [dict(row) | {"args": json.loads(row["args"]) if row["args"] else None} for row in rows]

    def append(self, chat_id: str, messages: list[dict]):
        with self.connection() as db:
            db.execute("begin immediate")
            if not db.execute("select 1 from chats where id=?", (chat_id,)).fetchone():
                raise LookupError("Чат не найден в локальном профиле")
            for message in messages:
                status = message.get("status", "legacy")
                if status not in {"legacy", "running", "completed", "cancelled", "failed"}:
                    raise ValueError("Некорректный статус сообщения")
                for key in ("id", "turn_id", "request_id"):
                    if message.get(key) is not None and (not isinstance(message[key], str) or not message[key]):
                        raise ValueError("Некорректный идентификатор сообщения")
                ordinal = message.get("event_index")
                if ordinal is not None and (type(ordinal) is not int or ordinal < 0):
                    raise ValueError("Некорректный номер события")
                existing = db.execute("select * from messages where id=? or "
                    "(chat_id=? and request_id=? and event_index=?)",
                    (message.get("id"), chat_id, message.get("request_id"), ordinal)).fetchall()
                if len(existing) > 1:
                    raise ValueError("Идентификаторы указывают на разные сообщения")
                previous = dict(existing[0]) if existing else None
                if ordinal is None:
                    ordinal = previous["event_index"] if previous else db.execute(
                        "select coalesce(max(event_index),-1)+1 from messages where chat_id=? and request_id is ?",
                        (chat_id, message.get("request_id"))).fetchone()[0]
                content, args = persistent_tool_message(message["role"], message.get("name"),
                                                        message.get("content", ""), message.get("args"))
                row = {"chat_id": chat_id, "role": message["role"], "content": content,
                       "name": message.get("name"), "args": json.dumps(args, sort_keys=True) if args is not None else None,
                       "call_id": message.get("call_id"), "thought_signature": message.get("thought_signature"),
                       "id": message.get("id") or (previous["id"] if previous else str(uuid4())),
                       "turn_id": message.get("turn_id"), "request_id": message.get("request_id"),
                       "event_index": ordinal, "status": status}
                if previous:
                    old_args = json.loads(previous["args"]) if previous["args"] is not None else None
                    previous["args"] = json.dumps(old_args, sort_keys=True) if old_args is not None else None
                    if any(previous[key] != value for key, value in row.items()):
                        raise ValueError("Повтор события отличается от сохранённого сообщения")
                    continue
                db.execute("""insert into messages(chat_id,role,content,name,args,call_id,thought_signature,
                              id,turn_id,request_id,event_index,status) values
                              (:chat_id,:role,:content,:name,:args,:call_id,:thought_signature,
                               :id,:turn_id,:request_id,:event_index,:status)""", row)

    def delete(self, chat_id: str) -> bool:
        with self.connection() as db:
            return db.execute("delete from chats where id=?", (chat_id,)).rowcount == 1

    def close(self):
        if self.memory is not None:
            self.memory.close()
