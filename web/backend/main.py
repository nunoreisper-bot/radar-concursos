from pathlib import Path
import sqlite3
from typing import Optional, Literal

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "radar.db"

app = FastAPI(title="Radar Concursos API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OpportunityUpdate(BaseModel):
    status: Literal["new", "favorite", "irrelevant", "review"]
    feedback_note: Optional[str] = None


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/health")
def health():
    return {"ok": True, "db": str(DB_PATH)}


@app.get("/opportunities")
def list_opportunities(
    min_score: int = Query(20, ge=0, le=100),
    category: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(500, ge=1, le=5000),
):
    sql = """
    SELECT id, notice_number, title, category, relevance_score, published_at, deadline_at,
           location, cpv, status, feedback_note, link
    FROM opportunities
    WHERE relevance_score >= ?
    """
    params = [min_score]

    if category and category != "todas":
        sql += " AND category = ?"
        params.append(category)
    if status and status != "todos":
        sql += " AND status = ?"
        params.append(status)
    if q:
        sql += " AND (lower(title) LIKE ? OR lower(cpv) LIKE ? OR lower(location) LIKE ? OR lower(notice_number) LIKE ?)"
        like = f"%{q.lower()}%"
        params.extend([like, like, like, like])

    sql += " ORDER BY first_seen_at DESC LIMIT ?"
    params.append(limit)

    conn = _conn()
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return {"items": rows, "count": len(rows)}


@app.get("/facets")
def facets():
    conn = _conn()
    categories = [r[0] for r in conn.execute("SELECT DISTINCT category FROM opportunities ORDER BY category").fetchall() if r[0]]
    statuses = [r[0] for r in conn.execute("SELECT DISTINCT status FROM opportunities ORDER BY status").fetchall() if r[0]]
    conn.close()
    return {"categories": categories, "statuses": statuses}


@app.patch("/opportunities/{item_id}")
def update_opportunity(item_id: int, payload: OpportunityUpdate):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE opportunities SET status = ?, feedback_note = ? WHERE id = ?",
        (payload.status, (payload.feedback_note or "").strip() or None, item_id),
    )
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return {"ok": changed > 0, "updated": changed}
