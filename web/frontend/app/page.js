"use client";

import { useEffect, useMemo, useState } from "react";

const API = "http://127.0.0.1:8000";

export default function Page() {
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("todas");
  const [status, setStatus] = useState("todos");
  const [minScore, setMinScore] = useState(20);

  const load = async () => {
    const params = new URLSearchParams({ min_score: String(minScore), limit: "1500" });
    if (q) params.set("q", q);
    if (category !== "todas") params.set("category", category);
    if (status !== "todos") params.set("status", status);
    const r = await fetch(`${API}/opportunities?${params.toString()}`);
    const data = await r.json();
    setItems(data.items || []);
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, status, minScore]);

  const categories = useMemo(() => ["todas", ...Array.from(new Set(items.map(i => i.category).filter(Boolean)))], [items]);

  const updateRow = async (id, patch) => {
    await fetch(`${API}/opportunities/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  };

  return (
    <div className="container">
      <h1>📡 Radar de Concursos — TED</h1>
      <div className="controls">
        <input placeholder="pesquisar..." value={q} onChange={(e) => setQ(e.target.value)} />
        <button onClick={load}>Procurar</button>
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {["todos", "new", "favorite", "irrelevant", "review"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input type="number" min={0} max={100} value={minScore} onChange={(e) => setMinScore(Number(e.target.value || 0))} />
      </div>

      <table>
        <thead>
          <tr>
            <th>aviso</th><th>título</th><th>categoria</th><th>score</th><th>aviso</th><th>entrega</th><th>localização</th><th>estado</th><th>nota</th><th>link</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td>{r.notice_number}</td>
              <td>{r.title}</td>
              <td>{r.category}</td>
              <td>{r.relevance_score}</td>
              <td>{r.published_at || "-"}</td>
              <td>{r.deadline_at || "-"}</td>
              <td>{r.location || "-"}</td>
              <td>
                <select
                  className={`badge ${r.status || "new"}`}
                  defaultValue={r.status || "new"}
                  onChange={(e) => updateRow(r.id, { status: e.target.value, feedback_note: r.feedback_note || "" })}
                >
                  {['new', 'favorite', 'irrelevant', 'review'].map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </td>
              <td>
                <input
                  defaultValue={r.feedback_note || ""}
                  onBlur={(e) => updateRow(r.id, { status: r.status || "new", feedback_note: e.target.value })}
                />
              </td>
              <td><a href={r.link} target="_blank">abrir</a></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
