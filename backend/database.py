import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(os.getenv("CDE_DB_PATH", Path(__file__).with_name("cde.db")))


def get_connection() -> sqlite3.Connection:
    """Create a SQLite connection with rows returned as dictionaries."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Initialize database tables if they do not exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS elements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                ifc_guid TEXT NOT NULL,
                element_code TEXT,
                element_name TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, model_id, ifc_guid)
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                element_id INTEGER NOT NULL,
                file_name TEXT,
                file_url TEXT NOT NULL,
                document_type TEXT,
                revision TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(element_id) REFERENCES elements(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_elements_lookup
                ON elements(project_id, model_id, ifc_guid);

            CREATE INDEX IF NOT EXISTS idx_documents_element
                ON documents(element_id);
            """
        )


def row_to_dict(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return dict(row)


def get_or_create_element(
    *,
    project_id: str,
    model_id: str,
    ifc_guid: str,
    element_code: Optional[str] = None,
    element_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Return existing BIM element or create it."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM elements
            WHERE project_id = ? AND model_id = ? AND ifc_guid = ?
            """,
            (project_id, model_id, ifc_guid),
        ).fetchone()

        if row:
            # Update metadata if the new request provides richer information.
            conn.execute(
                """
                UPDATE elements
                SET element_code = COALESCE(NULLIF(?, ''), element_code),
                    element_name = COALESCE(NULLIF(?, ''), element_name),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (element_code or "", element_name or "", row["id"]),
            )
            row = conn.execute("SELECT * FROM elements WHERE id = ?", (row["id"],)).fetchone()
            return dict(row)

        cur = conn.execute(
            """
            INSERT INTO elements (project_id, model_id, ifc_guid, element_code, element_name)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, model_id, ifc_guid, element_code, element_name),
        )
        element_id = cur.lastrowid
        row = conn.execute("SELECT * FROM elements WHERE id = ?", (element_id,)).fetchone()
        return dict(row)


def get_element(project_id: str, model_id: str, ifc_guid: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM elements
            WHERE project_id = ? AND model_id = ? AND ifc_guid = ?
            """,
            (project_id, model_id, ifc_guid),
        ).fetchone()
        return row_to_dict(row)


def add_document(
    *,
    project_id: str,
    model_id: str,
    ifc_guid: str,
    element_code: Optional[str],
    element_name: Optional[str],
    file_name: Optional[str],
    file_url: str,
    document_type: Optional[str],
    revision: Optional[str],
) -> Dict[str, Any]:
    element = get_or_create_element(
        project_id=project_id,
        model_id=model_id,
        ifc_guid=ifc_guid,
        element_code=element_code,
        element_name=element_name,
    )
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO documents (element_id, file_name, file_url, document_type, revision)
            VALUES (?, ?, ?, ?, ?)
            """,
            (element["id"], file_name, file_url, document_type, revision),
        )
        doc_id = cur.lastrowid
        row = conn.execute(
            """
            SELECT d.*, e.project_id, e.model_id, e.ifc_guid, e.element_code, e.element_name
            FROM documents d
            JOIN elements e ON e.id = d.element_id
            WHERE d.id = ?
            """,
            (doc_id,),
        ).fetchone()
        return dict(row)


def list_documents(project_id: str, model_id: str, ifc_guid: str) -> Dict[str, Any]:
    element = get_element(project_id, model_id, ifc_guid)
    if not element:
        return {
            "project_id": project_id,
            "model_id": model_id,
            "ifc_guid": ifc_guid,
            "element_code": None,
            "element_name": None,
            "documents": [],
        }

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, file_name, file_url, document_type, revision, status, created_at, updated_at
            FROM documents
            WHERE element_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (element["id"],),
        ).fetchall()

    return {
        "project_id": project_id,
        "model_id": model_id,
        "ifc_guid": ifc_guid,
        "element_code": element.get("element_code"),
        "element_name": element.get("element_name"),
        "documents": [dict(r) for r in rows],
    }


def delete_document(document_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return cur.rowcount > 0


def upsert_element(
    *,
    project_id: str,
    model_id: str,
    ifc_guid: str,
    element_code: Optional[str],
    element_name: Optional[str] = None,
) -> Dict[str, Any]:
    return get_or_create_element(
        project_id=project_id,
        model_id=model_id,
        ifc_guid=ifc_guid,
        element_code=element_code,
        element_name=element_name,
    )


def list_elements(project_id: str | None = None, model_id: str | None = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM elements WHERE 1=1"
    params: list[Any] = []
    if project_id:
        sql += " AND project_id = ?"
        params.append(project_id)
    if model_id:
        sql += " AND model_id = ?"
        params.append(model_id)
    sql += " ORDER BY created_at DESC, id DESC"

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
