from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY, messages TEXT NOT NULL DEFAULT '[]',
                    busy_until REAL NOT NULL DEFAULT 0, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS reports (
                    id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, document TEXT NOT NULL,
                    pdf BLOB NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
                    mail_status TEXT NOT NULL DEFAULT 'ready', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS limits (
                    key TEXT NOT NULL, bucket INTEGER NOT NULL, count INTEGER NOT NULL,
                    PRIMARY KEY(key, bucket));
                """
            )
            db.execute("INSERT OR IGNORE INTO settings VALUES ('secret', ?)", (secrets.token_hex(32),))
        os.chmod(path, 0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def secret(self) -> str:
        with self.connect() as db:
            return db.execute("SELECT value FROM settings WHERE key='secret'").fetchone()["value"]

    def messages(self, chat_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO chats(id, updated) VALUES (?, ?)", (chat_id, time.time()))
            return json.loads(db.execute("SELECT messages FROM chats WHERE id=?", (chat_id,)).fetchone()["messages"])

    def claim_chat(self, chat_id: str) -> bool:
        self.messages(chat_id)
        now = time.time()
        with self.connect() as db:
            return db.execute(
                "UPDATE chats SET busy_until=? WHERE id=? AND busy_until<?",
                (now + 180, chat_id, now),
            ).rowcount == 1

    def recent_chats(self, chat_ids: list[str]) -> list[dict[str, Any]]:
        if not chat_ids:
            return []
        placeholders = ",".join("?" for _ in chat_ids)
        with self.connect() as db:
            rows = db.execute(
                f"SELECT id, messages FROM chats WHERE id IN ({placeholders}) ORDER BY updated DESC",
                chat_ids,
            ).fetchall()
        result = []
        for row in rows:
            messages = json.loads(row["messages"])
            first = next((message for message in messages if message["role"] == "user"), None)
            if first:
                result.append({"id": row["id"], "title": first["content"][:100]})
        return result

    def release_chat(self, chat_id: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE chats SET busy_until=0 WHERE id=?", (chat_id,))

    def save_turn(self, chat_id: str, question: str, answer: str, report_id: str | None) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT messages FROM chats WHERE id=?", (chat_id,)).fetchone()
            messages = json.loads(row["messages"])
            messages.extend([
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer, "report_id": report_id},
            ])
            db.execute("UPDATE chats SET messages=?, updated=? WHERE id=?", (json.dumps(messages[-40:]), time.time(), chat_id))

    def save_report(self, report_id: str, chat_id: str, document: dict[str, Any], pdf: bytes) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO reports(id, chat_id, document, pdf, created) VALUES (?, ?, ?, ?, ?)",
                       (report_id, chat_id, json.dumps(document), pdf, time.time()))

    def report(self, report_id: str, chat_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM reports WHERE id=? AND chat_id=?", (report_id, chat_id)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["document"] = json.loads(result["document"])
            return result

    def review(self, report_id: str, chat_id: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE reports SET reviewed=1 WHERE id=? AND chat_id=?", (report_id, chat_id))

    def claim_email(self, report_id: str, chat_id: str) -> bool:
        with self.connect() as db:
            return db.execute(
                "UPDATE reports SET mail_status='sending' WHERE id=? AND chat_id=? "
                "AND reviewed=1 AND mail_status IN ('ready','failed')",
                (report_id, chat_id),
            ).rowcount == 1

    def email_status(self, report_id: str, chat_id: str, status: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE reports SET mail_status=? WHERE id=? AND chat_id=?", (status, report_id, chat_id))

    def allow(self, key: str, maximum: int, seconds: int) -> bool:
        key = f"{seconds}:{key}"
        bucket = int(time.time()) // seconds
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO limits VALUES (?, ?, 0)", (key, bucket))
            return db.execute(
                "UPDATE limits SET count=count+1 WHERE key=? AND bucket=? AND count<?",
                (key, bucket, maximum),
            ).rowcount == 1

    def cleanup(self) -> None:
        with self.connect() as db:
            cutoff = time.time() - 7 * 86400
            db.execute("DELETE FROM reports WHERE created<?", (cutoff,))
            db.execute("DELETE FROM chats WHERE updated<? AND busy_until<?", (cutoff, time.time()))
            db.execute(
                "DELETE FROM limits WHERE (bucket+1) * CAST(substr(key, 1, instr(key, ':')-1) AS INTEGER) < ?",
                (time.time() - 3600,),
            )
