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
            if db.execute("pragma user_version").fetchone()[0] > 1:
                raise ValueError("Локальная БД создана более новой версией приложения")
            db.executescript('''
                create table if not exists chats (
                    id text primary key, title text not null, created_at text not null);
                create table if not exists messages (
                    sequence integer primary key autoincrement,
                    chat_id text not null references chats(id) on delete cascade,
                    role text not null check (role in ('user','model','tool')),
                    content text not null, name text, args text, call_id text, thought_signature text);
                pragma user_version=1;
            ''')

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
        return [{key: row[key] for key in ("role", "content", "name", "call_id", "thought_signature")}
                | {"args": json.loads(row["args"]) if row["args"] else None} for row in rows]

    def append(self, chat_id: str, messages: list[dict]):
        with self.connection() as db:
            for message in messages:
                content, args = persistent_tool_message(message["role"], message.get("name"),
                                                        message.get("content", ""), message.get("args"))
                db.execute("""insert into messages(chat_id,role,content,name,args,call_id,thought_signature)
                              values (?,?,?,?,?,?,?)""", (chat_id, message["role"], content, message.get("name"),
                              json.dumps(args) if args is not None else None,
                              message.get("call_id"), message.get("thought_signature")))

    def delete(self, chat_id: str) -> bool:
        with self.connection() as db:
            return db.execute("delete from chats where id=?", (chat_id,)).rowcount == 1

    def close(self):
        if self.memory is not None:
            self.memory.close()
