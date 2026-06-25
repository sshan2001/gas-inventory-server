# -*- coding: utf-8 -*-
"""
Gas Inventory Server API v0.1.3
Render 배포용 Flask 서버 파일

수정 내용:
- /api/v1/sync/push 500 방지용 예외 처리 강화
- server_revision 저장 SQL 파라미터 오류 수정
- Render 환경에서 SQLite 경로를 /tmp 쪽으로 안전하게 정리
- 서버 오류 발생 시 JSON으로 상세 오류 반환
- /api/v1/debug/db 점검 API 추가

Render 설정:
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
"""

import json
import os
import sqlite3
import traceback
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS


APP_VERSION = "server-v0.1.3"


def resolve_db_path():
    raw = os.environ.get("GAS_INVENTORY_DB", "gas_inventory_server.sqlite3").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = Path("/tmp") / path.name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


DB_PATH = resolve_db_path()

app = Flask(__name__)
CORS(app)


def now_text():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def json_error(message, status=500, exc=None):
    payload = {
        "ok": False,
        "error": str(message),
        "version": APP_VERSION,
        "server_time": now_text(),
    }
    if exc is not None:
        payload["exception"] = exc.__class__.__name__
        payload["trace"] = traceback.format_exc()[-2500:]
        print("[SERVER ERROR]", traceback.format_exc(), flush=True)
    return jsonify(payload), status


def get_conn():
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                client_id TEXT PRIMARY KEY,
                app_version TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT '',
                user_role TEXT NOT NULL DEFAULT '',
                user_name TEXT NOT NULL DEFAULT '',
                worker TEXT NOT NULL DEFAULT '',
                first_seen TEXT NOT NULL DEFAULT '',
                last_seen TEXT NOT NULL DEFAULT ''
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS sync_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL DEFAULT '',
                local_id INTEGER,
                created_at TEXT NOT NULL DEFAULT '',
                received_at TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT '',
                user_role TEXT NOT NULL DEFAULT '',
                user_name TEXT NOT NULL DEFAULT '',
                worker TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL DEFAULT '{}'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS latest_snapshot (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                client_id TEXT NOT NULL DEFAULT '',
                server_revision INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT '',
                snapshot TEXT NOT NULL DEFAULT '{}'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS server_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            )
        """)

        cur.execute("""
            INSERT OR IGNORE INTO server_meta (key, value)
            VALUES ('server_revision', '0')
        """)

        conn.commit()


def get_server_revision(cur):
    cur.execute("SELECT value FROM server_meta WHERE key = 'server_revision'")
    row = cur.fetchone()
    try:
        return int(row["value"]) if row else 0
    except Exception:
        return 0


def set_server_revision(cur, revision):
    cur.execute("""
        INSERT INTO server_meta (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, ("server_revision", str(revision)))


def bump_server_revision(cur):
    revision = get_server_revision(cur) + 1
    set_server_revision(cur, revision)
    return revision


def require_json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"ok": False, "error": "JSON body is required"}), 400)
    return data, None


@app.get("/")
def index():
    try:
        init_db()
        return jsonify({
            "ok": True,
            "name": "Gas Inventory Server API",
            "version": APP_VERSION,
            "db_path": str(DB_PATH),
            "health": "/health",
            "endpoints": [
                "GET /health",
                "POST /api/v1/client/register",
                "POST /api/v1/sync/push",
                "GET /api/v1/sync/pull",
                "GET /api/v1/admin/events",
                "GET /api/v1/debug/db",
            ],
        })
    except Exception as exc:
        return json_error("index failed", 500, exc)


@app.get("/health")
def health():
    try:
        init_db()
        with get_conn() as conn:
            cur = conn.cursor()
            revision = get_server_revision(cur)
            cur.execute("SELECT COUNT(*) AS cnt FROM sync_events")
            event_count = cur.fetchone()["cnt"]

        return jsonify({
            "ok": True,
            "version": APP_VERSION,
            "server_time": now_text(),
            "server_revision": revision,
            "event_count": event_count,
            "db_path": str(DB_PATH),
        })
    except Exception as exc:
        return json_error("health failed", 500, exc)


@app.get("/api/v1/debug/db")
def debug_db():
    try:
        init_db()
        with get_conn() as conn:
            cur = conn.cursor()
            tables = {}
            for table in ["clients", "sync_events", "latest_snapshot", "server_meta"]:
                cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
                tables[table] = cur.fetchone()["cnt"]

        return jsonify({
            "ok": True,
            "version": APP_VERSION,
            "db_path": str(DB_PATH),
            "tables": tables,
            "server_time": now_text(),
        })
    except Exception as exc:
        return json_error("debug db failed", 500, exc)


@app.post("/api/v1/client/register")
def register_client():
    try:
        init_db()
        data, error = require_json()
        if error:
            return error

        client = data.get("client") or {}
        user = data.get("user") or {}

        client_id = str(client.get("client_id") or "").strip()
        if not client_id:
            return jsonify({"ok": False, "error": "client.client_id is required"}), 400

        app_version = str(client.get("app_version") or "")
        platform = str(client.get("platform") or "")
        user_role = str(user.get("role") or "")
        user_name = str(user.get("name") or "")
        worker = str(user.get("worker") or f"{user_role} {user_name}").strip()

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO clients
                (client_id, app_version, platform, user_role, user_name, worker, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    app_version = excluded.app_version,
                    platform = excluded.platform,
                    user_role = excluded.user_role,
                    user_name = excluded.user_name,
                    worker = excluded.worker,
                    last_seen = excluded.last_seen
            """, (
                client_id,
                app_version,
                platform,
                user_role,
                user_name,
                worker,
                now_text(),
                now_text()
            ))
            conn.commit()

        return jsonify({
            "ok": True,
            "client_id": client_id,
            "registered": True,
            "server_time": now_text(),
        })
    except Exception as exc:
        return json_error("client register failed", 500, exc)


@app.post("/api/v1/sync/push")
def sync_push():
    try:
        init_db()
        data, error = require_json()
        if error:
            return error

        client = data.get("client") or {}
        user = data.get("user") or {}
        events = data.get("events") or []
        snapshot = data.get("snapshot")

        client_id = str(client.get("client_id") or "").strip()
        if not client_id:
            return jsonify({"ok": False, "error": "client.client_id is required"}), 400

        if not isinstance(events, list):
            return jsonify({"ok": False, "error": "events must be a list"}), 400

        app_version = str(client.get("app_version") or "")
        platform = str(client.get("platform") or "")
        user_role = str(user.get("role") or "")
        user_name = str(user.get("name") or "")
        worker = str(user.get("worker") or f"{user_role} {user_name}").strip()

        accepted = 0

        with get_conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO clients
                (client_id, app_version, platform, user_role, user_name, worker, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    app_version = excluded.app_version,
                    platform = excluded.platform,
                    user_role = excluded.user_role,
                    user_name = excluded.user_name,
                    worker = excluded.worker,
                    last_seen = excluded.last_seen
            """, (
                client_id,
                app_version,
                platform,
                user_role,
                user_name,
                worker,
                now_text(),
                now_text()
            ))

            for event in events:
                if not isinstance(event, dict):
                    continue

                local_id = event.get("local_id")
                created_at = str(event.get("created_at") or "")
                event_type = str(event.get("event_type") or "unknown")
                payload = event.get("payload") or {}

                # 이벤트 payload 안에 스냅샷이 들어오면 중복 저장하지 않고 제거.
                if isinstance(payload, dict) and "snapshot" in payload:
                    payload = dict(payload)
                    payload.pop("snapshot", None)

                cur.execute("""
                    INSERT INTO sync_events
                    (client_id, local_id, created_at, received_at, event_type,
                     user_role, user_name, worker, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    client_id,
                    local_id if isinstance(local_id, int) else None,
                    created_at,
                    now_text(),
                    event_type,
                    user_role,
                    user_name,
                    worker,
                    json.dumps(payload, ensure_ascii=False)
                ))
                accepted += 1

            revision = bump_server_revision(cur)

            if isinstance(snapshot, dict):
                cur.execute("""
                    INSERT INTO latest_snapshot
                    (id, client_id, server_revision, updated_at, snapshot)
                    VALUES (1, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        client_id = excluded.client_id,
                        server_revision = excluded.server_revision,
                        updated_at = excluded.updated_at,
                        snapshot = excluded.snapshot
                """, (
                    client_id,
                    revision,
                    now_text(),
                    json.dumps(snapshot, ensure_ascii=False)
                ))

            conn.commit()

        return jsonify({
            "ok": True,
            "accepted": accepted,
            "server_revision": revision,
            "server_time": now_text(),
        })
    except Exception as exc:
        return json_error("sync push failed", 500, exc)


@app.get("/api/v1/sync/pull")
def sync_pull():
    try:
        init_db()

        since = request.args.get("since", default="0")
        try:
            since_id = int(since)
        except ValueError:
            since_id = 0

        with get_conn() as conn:
            cur = conn.cursor()
            revision = get_server_revision(cur)

            cur.execute("""
                SELECT id, client_id, local_id, created_at, received_at, event_type,
                       user_role, user_name, worker, payload
                FROM sync_events
                WHERE id > ?
                ORDER BY id
                LIMIT 500
            """, (since_id,))

            events = []
            for row in cur.fetchall():
                payload_text = row["payload"] or "{}"
                try:
                    payload = json.loads(payload_text)
                except Exception:
                    payload = {"raw": payload_text}

                events.append({
                    "server_event_id": row["id"],
                    "client_id": row["client_id"],
                    "local_id": row["local_id"],
                    "created_at": row["created_at"],
                    "received_at": row["received_at"],
                    "event_type": row["event_type"],
                    "user": {
                        "role": row["user_role"],
                        "name": row["user_name"],
                        "worker": row["worker"],
                    },
                    "payload": payload,
                })

            cur.execute("""
                SELECT client_id, server_revision, updated_at, snapshot
                FROM latest_snapshot
                WHERE id = 1
            """)
            snap_row = cur.fetchone()

        latest_snapshot = None
        if snap_row:
            try:
                latest_snapshot = json.loads(snap_row["snapshot"])
            except Exception:
                latest_snapshot = {"raw": snap_row["snapshot"]}

        return jsonify({
            "ok": True,
            "server_revision": revision,
            "server_time": now_text(),
            "events": events,
            "latest_snapshot": latest_snapshot,
            "snapshot_meta": {
                "client_id": snap_row["client_id"] if snap_row else "",
                "server_revision": snap_row["server_revision"] if snap_row else 0,
                "updated_at": snap_row["updated_at"] if snap_row else "",
            },
        })
    except Exception as exc:
        return json_error("sync pull failed", 500, exc)


@app.get("/api/v1/admin/events")
def admin_events():
    try:
        init_db()

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, client_id, created_at, received_at, event_type, worker, payload
                FROM sync_events
                ORDER BY id DESC
                LIMIT 100
            """)
            rows = [dict(row) for row in cur.fetchall()]

        return jsonify({
            "ok": True,
            "events": rows,
        })
    except Exception as exc:
        return json_error("admin events failed", 500, exc)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
