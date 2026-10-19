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
            self._append(db, chat_id, messages)

    def _append(self, db, chat_id: str, messages: list[dict]):
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

    def metadata(self, chat_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("select * from chats where id=?", (chat_id,)).fetchone()
            if row is None:
                raise LookupError("Чат не найден в локальном профиле")
            return dict(row)

    def claim_request(self, chat_id: str, request_id: str, turn_id: str) -> bool:
        if not all(isinstance(value, str) and value for value in (request_id, turn_id)):
            raise ValueError("Некорректный идентификатор запроса или хода")
        with self.connection() as db:
            db.execute("begin immediate")
            if not db.execute("select 1 from chats where id=?", (chat_id,)).fetchone():
                raise LookupError("Чат не найден в локальном профиле")
            existing = db.execute("select * from generation_requests where request_id=?", (request_id,)).fetchone()
            if existing:
                if existing["chat_id"] != chat_id or existing["turn_id"] != turn_id:
                    raise ValueError("Запрос уже принадлежит другому чату или ходу")
                return False
            return db.execute("""insert or ignore into generation_requests(request_id,chat_id,turn_id)
                              values (?,?,?)""", (request_id, chat_id, turn_id)).rowcount == 1

    def update_request_status(self, chat_id: str, request_id: str, status: str):
        if status not in {"running", "completed", "cancelled", "failed"}:
            raise ValueError("Некорректный статус запроса")
        with self.connection() as db:
            db.execute("begin immediate")
            row = db.execute("select status from generation_requests where chat_id=? and request_id=?",
                             (chat_id, request_id)).fetchone()
            if row is None:
                raise LookupError("Запрос не найден в локальном чате")
            if row["status"] == status:
                return
            if row["status"] != "running":
                raise ValueError("Завершённый запрос не может сменить статус")
            db.execute("update generation_requests set status=? where chat_id=? and request_id=?",
                       (status, chat_id, request_id))
            db.execute("update messages set status=? where chat_id=? and request_id=? and status='running'",
                       (status, chat_id, request_id))

    def set_summary(self, chat_id: str, summary: str, boundary_id: str):
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("Сводка должна содержать текст")
        with self.connection() as db:
            db.execute("begin immediate")
            if not db.execute("select 1 from chats where id=?", (chat_id,)).fetchone():
                raise LookupError("Чат не найден в локальном профиле")
            boundary = db.execute("select * from messages where chat_id=? and id=?",
                                  (chat_id, boundary_id)).fetchone()
            if boundary is None:
                raise LookupError("Граница сводки не найдена в локальном чате")
            last_user = db.execute("select max(sequence) from messages where chat_id=? and role='user'",
                                   (chat_id,)).fetchone()[0]
            self._check_boundary(db, chat_id, boundary)
            if last_user is None or boundary["sequence"] >= last_user:
                raise ValueError("Сводка должна сохранять последний ход целиком")
            previous = db.execute("""select sequence from messages where chat_id=? and id=(
                select summary_boundary from chats where id=?)""", (chat_id, chat_id)).fetchone()
            if previous and boundary["sequence"] < previous["sequence"]:
                raise ValueError("Граница сводки не может перемещаться назад")
            db.execute("update chats set summary=?,summary_boundary=? where id=?", (summary, boundary_id, chat_id))

    @staticmethod
    def _check_boundary(db, chat_id: str, boundary):
        if (not boundary["turn_id"] or boundary["role"] != "model" or boundary["name"]
                or boundary["status"] != "completed"):
            raise ValueError("Граница должна завершать полный ход")
        unsafe = db.execute("""select 1 from messages where chat_id=? and turn_id=?
            and (status!='completed' or sequence>?) limit 1""",
            (chat_id, boundary["turn_id"], boundary["sequence"])).fetchone()
        user = db.execute("select 1 from messages where chat_id=? and turn_id=? and role='user'",
                          (chat_id, boundary["turn_id"])).fetchone()
        if unsafe or not user:
            raise ValueError("Граница разрывает незавершённый ход")
        pending = []
        turn = db.execute("select role,name,call_id from messages where chat_id=? and turn_id=? order by sequence",
                          (chat_id, boundary["turn_id"]))
        for row in turn:
            if row["role"] == "model" and row["name"]:
                pending.append((row["name"], row["call_id"]))
            elif row["role"] == "tool":
                matches = [call for call in pending if call[0] == row["name"]
                           and (row["call_id"] is None or call[1] == row["call_id"])]
                if len(matches) != 1:
                    raise ValueError("Ход содержит несвязанный результат инструмента")
                pending.remove(matches[0])
        if pending:
            raise ValueError("Ход содержит вызов инструмента без результата")

    def fork(self, chat_id: str, title: str, boundary_id: str | None = None) -> dict:
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("Некорректное название чата")
        with self.connection() as db:
            db.execute("begin immediate")
            parent = db.execute("select * from chats where id=?", (chat_id,)).fetchone()
            if parent is None:
                raise LookupError("Чат не найден в локальном профиле")
            rows = db.execute("select * from messages where chat_id=? order by sequence", (chat_id,)).fetchall()
            boundary = None
            for candidate in reversed(rows):
                if boundary_id is not None and candidate["id"] != boundary_id:
                    continue
                try:
                    self._check_boundary(db, chat_id, candidate)
                except ValueError:
                    if boundary_id is not None:
                        raise
                    continue
                boundary = candidate
                break
            if boundary is None:
                raise ValueError("Завершённая граница форка не найдена в локальном чате")
            prefix = [dict(row) for row in rows if row["sequence"] <= boundary["sequence"]]
            ids = {row["id"]: str(uuid4()) for row in prefix}
            for row in prefix:
                row["id"] = ids[row["id"]]
                row["args"] = json.loads(row["args"]) if row["args"] else None
            chat = {"id": str(uuid4()), "title": title.strip(),
                    "created_at": datetime.now(timezone.utc).isoformat(), "fork_parent_id": chat_id,
                    "fork_boundary": boundary["id"], "summary_boundary": ids.get(parent["summary_boundary"])}
            chat["summary"] = parent["summary"] if chat["summary_boundary"] else None
            db.execute("""insert into chats(id,title,created_at,fork_parent_id,fork_boundary,summary,summary_boundary)
                values (:id,:title,:created_at,:fork_parent_id,:fork_boundary,:summary,:summary_boundary)""", chat)
            self._append(db, chat["id"], prefix)
            return chat

    def delete(self, chat_id: str) -> bool:
        with self.connection() as db:
            return db.execute("delete from chats where id=?", (chat_id,)).rowcount == 1

    def close(self):
        if self.memory is not None:
            self.memory.close()
