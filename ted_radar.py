import hashlib
import html
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional

import requests

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

DB_PATH = os.path.join(os.path.dirname(__file__), "radar.db")
DATABASE_URL = os.getenv("DATABASE_URL")
SEM_API = "https://tedweb.api.ted.europa.eu/private-search/api/v1/notices/search"
VIEWER_API = "https://tedweb.api.ted.europa.eu/viewer/api/v1/render"
# Optional BASE feed endpoint (JSON). Set this in env to enable BASE ingestion.
BASE_API_URL = os.getenv("BASE_API_URL", "").strip()

SEARCH_QUERIES = [
    "(FT IN (architecture)) AND (buyer-country IN (PRT)) SORT BY ND DESC",
    "(FT IN (architectural)) AND (buyer-country IN (PRT)) SORT BY ND DESC",
    "(FT IN (arquitetura)) AND (buyer-country IN (PRT)) SORT BY ND DESC",
    "(PC IN (71000000)) AND (buyer-country IN (PRT)) SORT BY ND DESC",
    "(PC IN (71200000)) AND (buyer-country IN (PRT)) SORT BY ND DESC",
]

API_FIELDS = [
    "publication-number",
    "notice-title",
    "publication-date",
    "deadline-receipt-request",
    "classification-cpv",
    "place-of-performance",
    "total-value",
    "TV",
    "award-criterion-type-lot",
    "award-criterion-type-part",
    "ND",
    "TI",
    "PD",
    "DT",
    "PC",
]

KEYWORDS = {
    "arquitectura": 24,
    "arquitetura": 24,
    "architecture": 24,
    "architectural": 24,
    "engenharia": 10,
    "engineering": 10,
    "projecto": 8,
    "projeto": 8,
    "design": 8,
    "fiscalização": 10,
    "fiscalizacao": 10,
    "construction management": 8,
    "urbanismo": 8,
}


@dataclass
class Opportunity:
    source: str
    notice_number: str
    title: str
    description: str
    entity: str
    country: str
    location: Optional[str]
    cpv: Optional[str]
    estimated_value: Optional[str]
    criterion: Optional[str]
    published_at: Optional[str]
    deadline_at: Optional[str]
    link: str
    category: str
    relevance_score: int
    hash_id: str


def _is_postgres() -> bool:
    return bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))


def _connect():
    if _is_postgres():
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is set")
        return psycopg.connect(DATABASE_URL)
    return sqlite3.connect(DB_PATH)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_db() -> None:
    conn = _connect()
    cur = conn.cursor()

    if _is_postgres():
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS opportunities (
                id BIGSERIAL PRIMARY KEY,
                hash_id TEXT UNIQUE,
                source TEXT NOT NULL,
                notice_number TEXT,
                title TEXT NOT NULL,
                description TEXT,
                entity TEXT,
                country TEXT,
                location TEXT,
                cpv TEXT,
                estimated_value TEXT,
                criterion TEXT,
                published_at TEXT,
                deadline_at TEXT,
                link TEXT NOT NULL,
                category TEXT,
                relevance_score INTEGER DEFAULT 0,
                status TEXT DEFAULT 'new',
                feedback_note TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        cur.execute("ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS notice_number TEXT")
        cur.execute("ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS location TEXT")
        cur.execute("ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS feedback_note TEXT")
        cur.execute("ALTER TABLE opportunities ADD COLUMN IF NOT EXISTS criterion TEXT")
    else:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hash_id TEXT UNIQUE,
                source TEXT NOT NULL,
                notice_number TEXT,
                title TEXT NOT NULL,
                description TEXT,
                entity TEXT,
                country TEXT,
                location TEXT,
                cpv TEXT,
                estimated_value TEXT,
                criterion TEXT,
                published_at TEXT,
                deadline_at TEXT,
                link TEXT NOT NULL,
                category TEXT,
                relevance_score INTEGER DEFAULT 0,
                status TEXT DEFAULT 'new',
                feedback_note TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        existing_cols = {r[1] for r in cur.execute("PRAGMA table_info(opportunities)").fetchall()}
        if "notice_number" not in existing_cols:
            cur.execute("ALTER TABLE opportunities ADD COLUMN notice_number TEXT")
        if "location" not in existing_cols:
            cur.execute("ALTER TABLE opportunities ADD COLUMN location TEXT")
        if "feedback_note" not in existing_cols:
            cur.execute("ALTER TABLE opportunities ADD COLUMN feedback_note TEXT")
        if "criterion" not in existing_cols:
            cur.execute("ALTER TABLE opportunities ADD COLUMN criterion TEXT")

    conn.commit()
    conn.close()


def _pick_title(raw: dict | str | None) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        for k in ("eng", "por", "pt", "en"):
            if raw.get(k):
                return str(raw[k]).strip()
        vals = [v for v in raw.values() if isinstance(v, str) and v.strip()]
        if vals:
            return vals[0].strip()
    return ""


def _extract_deadline(raw_deadline) -> Optional[str]:
    if isinstance(raw_deadline, list) and raw_deadline:
        first = raw_deadline[0]
        if isinstance(first, dict):
            return first.get("value") or first.get("label")
        return str(first)
    return None


def _extract_cpv(raw_cpv) -> Optional[str]:
    if isinstance(raw_cpv, list) and raw_cpv:
        vals = []
        for x in raw_cpv[:3]:
            if isinstance(x, dict):
                v = x.get("value")
                l = x.get("label")
                vals.append(f"{v}:{l}" if v and l else (v or l or ""))
            else:
                vals.append(str(x))
        return " | ".join([v for v in vals if v]) or None
    return None


def _extract_location(raw_location) -> Optional[str]:
    if isinstance(raw_location, list) and raw_location:
        parts = []
        for x in raw_location[:3]:
            if isinstance(x, dict):
                lbl = x.get("label") or x.get("value")
                if lbl:
                    parts.append(lbl)
            elif x:
                parts.append(str(x))
        if parts:
            return " | ".join(parts)
    return None


def _extract_simple(raw_value) -> Optional[str]:
    if isinstance(raw_value, str):
        return raw_value.strip() or None
    if isinstance(raw_value, (int, float)):
        return str(raw_value)
    if isinstance(raw_value, list) and raw_value:
        vals = []
        for x in raw_value[:3]:
            if isinstance(x, dict):
                v = x.get("label") or x.get("value")
                if v:
                    vals.append(str(v))
            elif x:
                vals.append(str(x))
        return " | ".join(vals) if vals else None
    if isinstance(raw_value, dict):
        for k in ("label", "value", "eng", "por"):
            if raw_value.get(k):
                return str(raw_value[k])
    return None


def _strip_html(s: str) -> str:
    t = re.sub(r"<[^>]+>", " ", s or "")
    t = html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _fetch_notice_enrichment(publication_number: str) -> tuple[Optional[str], Optional[str]]:
    try:
        url = f"{VIEWER_API}/{publication_number}/html?language=EN"
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return None, None
        data = r.json()
        summary = _strip_html(data.get("summary", ""))
        full = _strip_html(data.get("noticeAsHtml", ""))

        estimated = None
        m_est = re.search(r"Estimated value excluding VAT\s*:?\s*([^:]{1,80}?\sEUR)", summary, flags=re.IGNORECASE)
        if not m_est:
            m_est = re.search(r"Estimated value excluding VAT\s*:?\s*([^:]{1,80}?\sEUR)", full, flags=re.IGNORECASE)
        if m_est:
            estimated = m_est.group(1).strip()

        criterion = None
        m_crit = re.search(r"Award criteria.*?Type\s*:\s*([A-Za-zÀ-ÿ\-\s]{2,40})", full, flags=re.IGNORECASE)
        if m_crit:
            criterion = m_crit.group(1).strip()
        else:
            m_crit2 = re.search(r"Award criteria\s*:\s*([A-Za-zÀ-ÿ\-\s]{3,80})", full, flags=re.IGNORECASE)
            if m_crit2:
                criterion = m_crit2.group(1).strip()

        if criterion:
            criterion = criterion.replace(" Name", "").strip()

        return estimated, criterion
    except Exception:
        return None, None


def _score_and_category(title: str, description: str, cpv: Optional[str]) -> tuple[int, str]:
    t = f"{title} {description} {cpv or ''}".lower()
    score = 0
    for kw, w in KEYWORDS.items():
        if kw in t:
            score += w

    if "architecture" in t or "arquitetura" in t or "arquitectura" in t:
        category = "arquitetura"
    elif "engineering" in t or "engenharia" in t:
        category = "engenharia"
    elif "fiscal" in t:
        category = "fiscalização"
    else:
        category = "misto"

    return min(score, 100), category


def _hash_for_item(title: str, link: str) -> str:
    return hashlib.sha256(f"{title}|{link}".encode("utf-8")).hexdigest()


def _post_search(query: str, page: int, limit: int = 50) -> list[dict]:
    payload = {
        "query": query,
        "page": page,
        "limit": limit,
        "scope": "ALL",
        "language": "EN",
        "onlyLatestVersions": False,
        "validation": False,
        "fields": API_FIELDS,
    }
    r = requests.post(
        SEM_API,
        json=payload,
        timeout=40,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    if r.status_code != 200:
        return []
    return r.json().get("notices", [])


def fetch_ted_opportunities(max_pages_per_query: int = 4) -> List[Opportunity]:
    opportunities: List[Opportunity] = []
    seen = set()

    for q in SEARCH_QUERIES:
        for page in range(1, max_pages_per_query + 1):
            notices = _post_search(q, page=page, limit=50)
            if not notices:
                break

            for n in notices:
                pub_no = n.get("publication-number") or n.get("ND")
                if not pub_no:
                    continue

                title = _pick_title(n.get("notice-title") or n.get("TI"))
                if not title:
                    continue

                link = f"https://ted.europa.eu/en/notice/-/detail/{pub_no}"
                h = _hash_for_item(title, link)
                if h in seen:
                    continue
                seen.add(h)

                cpv = _extract_cpv(n.get("classification-cpv") or n.get("PC"))
                deadline = _extract_deadline(n.get("deadline-receipt-request") or n.get("DT"))
                published = n.get("publication-date") or n.get("PD")
                location = _extract_location(n.get("place-of-performance"))
                base_price = _extract_simple(n.get("total-value") or n.get("TV"))
                criterion = _extract_simple(n.get("award-criterion-type-lot") or n.get("award-criterion-type-part"))
                score, category = _score_and_category(title, "", cpv)

                opportunities.append(
                    Opportunity(
                        source="TED",
                        notice_number=pub_no,
                        title=title,
                        description="",
                        entity=title.split(":", 1)[0].strip() if ":" in title else "",
                        country="Portugal",
                        location=location,
                        cpv=cpv,
                        estimated_value=base_price,
                        criterion=criterion,
                        published_at=published,
                        deadline_at=deadline,
                        link=link,
                        category=category,
                        relevance_score=score,
                        hash_id=h,
                    )
                )

    return opportunities


def upsert_opportunities(items: Iterable[Opportunity]) -> int:
    ensure_db()
    now = _now_iso()
    conn = _connect()
    cur = conn.cursor()
    inserted = 0

    if _is_postgres():
        for o in items:
            cur.execute(
                """
                INSERT INTO opportunities (
                    hash_id, source, notice_number, title, description, entity, country, location, cpv, estimated_value, criterion,
                    published_at, deadline_at, link, category, relevance_score, first_seen_at, last_seen_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (hash_id) DO UPDATE SET
                    last_seen_at = EXCLUDED.last_seen_at,
                    relevance_score = EXCLUDED.relevance_score,
                    category = EXCLUDED.category,
                    cpv = EXCLUDED.cpv,
                    deadline_at = EXCLUDED.deadline_at,
                    published_at = EXCLUDED.published_at,
                    location = EXCLUDED.location,
                    notice_number = EXCLUDED.notice_number,
                    estimated_value = EXCLUDED.estimated_value,
                    criterion = EXCLUDED.criterion
                RETURNING (xmax = 0) AS inserted
                """,
                (
                    o.hash_id,
                    o.source,
                    o.notice_number,
                    o.title,
                    o.description,
                    o.entity,
                    o.country,
                    o.location,
                    o.cpv,
                    o.estimated_value,
                    o.criterion,
                    o.published_at,
                    o.deadline_at,
                    o.link,
                    o.category,
                    o.relevance_score,
                    now,
                    now,
                ),
            )
            row = cur.fetchone()
            if row and row[0]:
                inserted += 1
    else:
        for o in items:
            cur.execute("SELECT id FROM opportunities WHERE hash_id = ?", (o.hash_id,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    """
                    UPDATE opportunities
                    SET last_seen_at = ?, relevance_score = ?, category = ?, cpv = ?,
                        deadline_at = ?, published_at = ?, location = ?, notice_number = ?,
                        estimated_value = ?, criterion = ?
                    WHERE hash_id = ?
                    """,
                    (
                        now,
                        o.relevance_score,
                        o.category,
                        o.cpv,
                        o.deadline_at,
                        o.published_at,
                        o.location,
                        o.notice_number,
                        o.estimated_value,
                        o.criterion,
                        o.hash_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO opportunities (
                        hash_id, source, notice_number, title, description, entity, country, location, cpv, estimated_value, criterion,
                        published_at, deadline_at, link, category, relevance_score, first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        o.hash_id,
                        o.source,
                        o.notice_number,
                        o.title,
                        o.description,
                        o.entity,
                        o.country,
                        o.location,
                        o.cpv,
                        o.estimated_value,
                        o.criterion,
                        o.published_at,
                        o.deadline_at,
                        o.link,
                        o.category,
                        o.relevance_score,
                        now,
                        now,
                    ),
                )
                inserted += 1

    conn.commit()
    conn.close()
    return inserted


def enrich_missing_fields(limit: int = 150) -> int:
    ensure_db()
    conn = _connect()
    cur = conn.cursor()

    if _is_postgres():
        cur.execute(
            """
            SELECT id, notice_number, estimated_value, criterion
            FROM opportunities
            WHERE (estimated_value IS NULL OR estimated_value = '' OR criterion IS NULL OR criterion = '')
              AND notice_number IS NOT NULL
            ORDER BY first_seen_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    else:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT id, notice_number, estimated_value, criterion
            FROM opportunities
            WHERE (estimated_value IS NULL OR estimated_value = '' OR criterion IS NULL OR criterion = '')
              AND notice_number IS NOT NULL
            ORDER BY first_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    updated = 0
    for r in rows:
        rid = r[0] if _is_postgres() else r["id"]
        notice = r[1] if _is_postgres() else r["notice_number"]
        old_est = r[2] if _is_postgres() else r["estimated_value"]
        old_crit = r[3] if _is_postgres() else r["criterion"]

        est, crit = _fetch_notice_enrichment(notice)
        if not est and not crit:
            continue
        new_est = est or old_est
        new_crit = crit or old_crit

        if _is_postgres():
            cur.execute(
                "UPDATE opportunities SET estimated_value = %s, criterion = %s WHERE id = %s",
                (new_est, new_crit, rid),
            )
        else:
            cur.execute(
                "UPDATE opportunities SET estimated_value = ?, criterion = ? WHERE id = ?",
                (new_est, new_crit, rid),
            )
        updated += 1

    conn.commit()
    conn.close()
    return updated


def fetch_base_opportunities(limit: int = 200) -> List[Opportunity]:
    """
    Optional BASE ingestion via JSON endpoint configured in BASE_API_URL.
    Expected payload: list[dict] or {"items": list[dict]} with common keys.
    """
    if not BASE_API_URL:
        return []

    try:
        r = requests.get(BASE_API_URL, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        payload = r.json()
    except Exception:
        return []

    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []

    out: List[Opportunity] = []
    seen = set()
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue

        title = str(row.get("title") or row.get("designacao") or row.get("objetoContrato") or "").strip()
        link = str(row.get("url") or row.get("link") or row.get("href") or "").strip()
        notice_number = str(row.get("notice_number") or row.get("numeroAnuncio") or row.get("id") or "").strip()
        entity = str(row.get("entity") or row.get("entidade") or row.get("adjudicante") or "").strip()
        location = str(row.get("location") or row.get("local") or row.get("distrito") or "").strip() or None
        cpv = str(row.get("cpv") or row.get("codigoCPV") or "").strip() or None
        published = str(row.get("published_at") or row.get("dataPublicacao") or row.get("publicationDate") or "").strip() or None
        deadline = str(row.get("deadline_at") or row.get("prazo") or row.get("deadline") or "").strip() or None
        estimated = str(row.get("estimated_value") or row.get("precoBase") or row.get("valor") or "").strip() or None
        criterion = str(row.get("criterion") or row.get("criterio") or "").strip() or None

        if not title:
            continue
        if not link:
            link = f"https://www.base.gov.pt/Base4/pt/" + (notice_number if notice_number else "")

        h = _hash_for_item(title, link)
        if h in seen:
            continue
        seen.add(h)

        score, category = _score_and_category(title, "", cpv)
        out.append(
            Opportunity(
                source="BASE",
                notice_number=notice_number,
                title=title,
                description="",
                entity=entity,
                country="Portugal",
                location=location,
                cpv=cpv,
                estimated_value=estimated,
                criterion=criterion,
                published_at=published,
                deadline_at=deadline,
                link=link,
                category=category,
                relevance_score=score,
                hash_id=h,
            )
        )

    return out


def run_sync() -> dict:
    ensure_db()
    ted_items = fetch_ted_opportunities()
    base_items = fetch_base_opportunities()
    items = ted_items + base_items
    inserted = upsert_opportunities(items)
    enriched = enrich_missing_fields(limit=120)
    return {
        "fetched": len(items),
        "fetched_ted": len(ted_items),
        "fetched_base": len(base_items),
        "inserted": inserted,
        "enriched": enriched,
    }


if __name__ == "__main__":
    result = run_sync()
    print(
        "Sync done. "
        f"fetched={result['fetched']} "
        f"(ted={result['fetched_ted']}, base={result['fetched_base']}) "
        f"inserted={result['inserted']} enriched={result['enriched']}"
    )
