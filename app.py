import csv
import io
from datetime import datetime

import pandas as pd
import streamlit as st

from ted_radar import DB_PATH, get_recent, run_sync, save_feedback

st.set_page_config(page_title="Radar de Concursos (TED)", layout="wide")

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&display=swap');

      .stApp, .stApp * {
        font-family: 'Playfair Display', Georgia, 'Times New Roman', serif !important;
      }

      .stApp {
        background: linear-gradient(180deg, #f8f7f4 0%, #f2efe9 100%);
        color: #1f2937 !important;
      }

      h1, h2, h3, p, label, span, div {
        color: #1f2937 !important;
      }

      h1, h2, h3 { letter-spacing: 0.2px; }

      [data-testid="stSidebar"] {
        background: #f3eee5;
      }

      .stButton > button {
        border-radius: 12px;
        border: 1px solid #8b6f47;
        background: #f6efe2;
      }

      /* data editor readability */
      div[data-testid="stDataFrame"] table tbody tr td {
        padding-top: 12px !important;
        padding-bottom: 12px !important;
        line-height: 1.35 !important;
      }

      .block-container {
        padding-top: 1.4rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📡 Radar de Concursos — TED (Portugal)")
st.caption("Tabela interativa com categorias, datas, localização, favoritos e feedback.")

ctl1, ctl2, ctl3 = st.columns([1, 1, 2])
with ctl1:
    min_score = st.slider("Score mínimo", min_value=0, max_value=100, value=20, step=5)
with ctl2:
    if st.button("🔄 Atualizar TED agora"):
        result = run_sync()
        st.success(f"Sincronizado. Lidos: {result['fetched']} · Novos: {result['inserted']}")
with ctl3:
    st.info("Marca favoritos e sinaliza o que não interessa. O feedback fica guardado para afinar o radar.")

rows = get_recent(min_score=min_score, limit=2000)
if not rows:
    st.warning("Sem resultados ainda. Clica em 'Atualizar TED agora'.")
    st.stop()

raw_df = pd.DataFrame([dict(r) for r in rows])

search = st.text_input("Pesquisar (título / CPV / localização / nº aviso)").strip().lower()
if search:
    mask = (
        raw_df["title"].fillna("").str.lower().str.contains(search)
        | raw_df["cpv"].fillna("").str.lower().str.contains(search)
        | raw_df["location"].fillna("").str.lower().str.contains(search)
        | raw_df["notice_number"].fillna("").str.lower().str.contains(search)
    )
    raw_df = raw_df[mask]

cat_col, status_col = st.columns(2)
with cat_col:
    categories = ["todas"] + sorted(raw_df["category"].dropna().unique().tolist())
    selected_category = st.selectbox("Categoria", categories)
with status_col:
    statuses = ["todos", "new", "favorite", "irrelevant", "review"]
    selected_status = st.selectbox("Estado", statuses)

if selected_category != "todas":
    raw_df = raw_df[raw_df["category"] == selected_category]
if selected_status != "todos":
    raw_df = raw_df[raw_df["status"].fillna("new") == selected_status]

st.subheader(f"Resultados ({len(raw_df)})")

tab_edit, tab_view = st.tabs(["✍️ Editar (favoritos/feedback)", "🎨 Vista bonita"])

view_df = raw_df[
    [
        "id",
        "notice_number",
        "title",
        "category",
        "relevance_score",
        "published_at",
        "deadline_at",
        "location",
        "cpv",
        "status",
        "feedback_note",
        "link",
    ]
].copy()

view_df.rename(
    columns={
        "notice_number": "aviso",
        "title": "título",
        "category": "categoria",
        "relevance_score": "score",
        "published_at": "data_aviso",
        "deadline_at": "data_entrega",
        "location": "localização",
        "cpv": "cpv",
        "status": "estado",
        "feedback_note": "nota",
        "link": "link",
    },
    inplace=True,
)

with tab_edit:
    edited = st.data_editor(
        view_df,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        height=760,
        column_config={
            "id": st.column_config.NumberColumn("id", disabled=True),
            "aviso": st.column_config.TextColumn("aviso", disabled=True),
            "título": st.column_config.TextColumn("título", width="large", disabled=True),
            "categoria": st.column_config.TextColumn("categoria", disabled=True),
            "score": st.column_config.NumberColumn("score", disabled=True),
            "data_aviso": st.column_config.TextColumn("data aviso", disabled=True),
            "data_entrega": st.column_config.TextColumn("data entrega", disabled=True),
            "localização": st.column_config.TextColumn("localização", disabled=True),
            "cpv": st.column_config.TextColumn("cpv", disabled=True),
            "estado": st.column_config.SelectboxColumn("estado", options=["new", "favorite", "irrelevant", "review"]),
            "nota": st.column_config.TextColumn("nota (feedback)", width="medium", help="Ex: não é arquitetura / muito industrial / relevante para nós"),
            "link": st.column_config.LinkColumn("link", display_text="abrir"),
        },
    )

with tab_view:
    pretty_df = view_df.copy()

    def _state_style(v):
        if v == "favorite":
            return "background-color: #d8f3dc; color: #1b4332; font-weight: 600;"
        if v == "irrelevant":
            return "background-color: #ffe5e5; color: #9d0208; font-weight: 600;"
        if v == "review":
            return "background-color: #fff3cd; color: #664d03; font-weight: 600;"
        return "background-color: #f1f3f5; color: #495057;"

    styler = pretty_df.style.applymap(_state_style, subset=["estado"])
    st.dataframe(styler, use_container_width=True, height=760)

if st.button("💾 Guardar favoritos/feedback"):
    updates = []
    for _, row in edited.iterrows():
        updates.append(
            {
                "id": int(row["id"]),
                "status": row.get("estado") or "new",
                "feedback_note": row.get("nota") or "",
            }
        )
    n = save_feedback(updates)
    st.success(f"Guardado. {n} linhas atualizadas.")

csv_buf = io.StringIO()
export_df = edited.copy()
writer = csv.DictWriter(csv_buf, fieldnames=list(export_df.columns))
writer.writeheader()
writer.writerows(export_df.to_dict(orient="records"))

st.download_button(
    "⬇️ Exportar CSV",
    data=csv_buf.getvalue().encode("utf-8"),
    file_name=f"radar_ted_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
    mime="text/csv",
)

st.caption(f"DB: {DB_PATH}")
