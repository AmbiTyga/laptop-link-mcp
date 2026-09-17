"""Durable mutation identities. Contains sensitive command/file payloads."""
import json
import os
import sqlite3
import stat
from pathlib import Path


class Journal:
    def __init__(self, directory: Path, scope: str):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("State directory must be owned by you and private (chmod 700)")
        path = directory / "requests.sqlite3"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("Journal must be owned by you and private (chmod 600)")
        finally:
            os.close(fd)
        self.db = sqlite3.connect(path)
        self.scope = scope
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS requests "
                        "(scope TEXT, id TEXT, request TEXT NOT NULL, response TEXT, "
                        "created TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(scope, id))")
        self.db.commit()

    def save(self, request: dict):
        with self.db:
            self.db.execute("INSERT INTO requests(scope,id,request) VALUES(?,?,?)",
                            (self.scope, request["id"], json.dumps(request)))

    def complete(self, request_id: str, response: dict):
        with self.db:
            self.db.execute("UPDATE requests SET response=? WHERE scope=? AND id=?",
                            (json.dumps(response), self.scope, request_id))

    def get(self, request_id: str) -> tuple[dict, dict | None]:
        row = self.db.execute("SELECT request,response FROM requests WHERE scope=? AND id=?",
                              (self.scope, request_id)).fetchone()
        if not row:
            raise ValueError("Unknown request ID for this enrolled device")
        return json.loads(row[0]), json.loads(row[1]) if row[1] else None

    def pending(self) -> list[dict]:
        rows = self.db.execute("SELECT id,request,created FROM requests WHERE scope=? "
                               "AND response IS NULL ORDER BY created DESC LIMIT 100", (self.scope,)).fetchall()
        return [{"request_id": row[0], "method": json.loads(row[1])["method"],
                 "bootID": json.loads(row[1])["bootID"], "created": row[2]} for row in rows]

    def close(self):
        self.db.close()
