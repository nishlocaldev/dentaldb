# app.py
import os, sqlite3, requests, hashlib
import pandas as pd
import streamlit as st

# =========================
# Password protection (env)
# =========================
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

def check_password():
    def password_entered():
        ok = hashlib.sha256(st.session_state["password"].encode()).hexdigest() == \
             hashlib.sha256(APP_PASSWORD.encode()).hexdigest()
        st.session_state["password_ok"] = ok
        # never keep raw password
        if "password" in st.session_state:
            del st.session_state["password"]

    if "password_ok" not in st.session_state:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        return False
    if not st.session_state["password_ok"]:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("❌ Wrong password")
        return False
    return True

if not check_password():
    st.stop()

# =========================
# Config / download DB once
# =========================
st.set_page_config(page_title="Business Directory", layout="wide")

DB_PATH = "data.db"
DB_URL = os.environ.get("DB_URL", "")  # e.g. Dropbox direct link with dl=1
DOWNLOAD_CHUNK = 1 << 14  # 16KB

CUSTOM_CSS = """
<style>
* { font-family: ui-sans-serif, -apple-system, system-ui, "SF Pro Text", "Helvetica Neue", Arial; }
.block-container { padding-top: 1.0rem; padding-bottom: 3.5rem; }

/* Header */
h1 { letter-spacing: -0.02em; margin-bottom: 0.15rem; }
.small-subtle { color:#6b7280; margin-bottom: 1.0rem; }

/* KPI cards */
.kpi { padding: 14px 16px; background: #ffffff; border: 1px solid #eee; border-radius: 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.04); }
.kpi .label { font-size: 0.82rem; color:#6b7280; }
.kpi .value { font-size: 1.4rem; font-weight: 700; margin-top: 2px; }

/* Table */
table { width: 100%; border-collapse: separate; border-spacing: 0; }
thead th { position: sticky; top: 0; background: #fff; border-bottom: 1px solid #eee; z-index: 2; }
tbody tr:nth-child(even) { background: #fafafa; }
td, th { padding: 10px 12px; vertical-align: top; white-space: nowrap; max-width: 420px; text-overflow: ellipsis; overflow: hidden; }
a { text-decoration: none; }

/* Footer */
.footer {
  position: fixed; left: 0; right: 0; bottom: 0;
  padding: 10px 16px; background: #f9fafb; border-top: 1px solid #eee;
  color: #6b7280; font-size: 0.9rem; text-align: center;
}

/* Pagination */
.pager { display:flex; gap:8px; align-items:center; justify-content:center; margin: 6px 0; }
.pager .info { color:#6b7280; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Download DB on first run (if not present)
if not os.path.exists(DB_PATH):
    if not DB_URL:
        st.error("DB_URL is not set. Please configure it in Streamlit secrets.")
        st.stop()
    st.info("Downloading database… first run may take a while.")
    try:
        with requests.get(DB_URL, stream=True, timeout=120) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", "0"))
            prog = st.progress(0)
            wrote = 0
            with open(DB_PATH, "wb") as f:
                for chunk in r.iter_content(chunk_size=DOWNLOAD_CHUNK):
                    if chunk:
                        f.write(chunk)
                        wrote += len(chunk)
                        if total:
                            prog.progress(min(1.0, wrote / total))
        st.success("Database downloaded.")
    except Exception as e:
        st.error(f"Failed to download DB: {e}")
        st.stop()

# =========================
# Helpers
# =========================
def get_columns(con, table):
    return set(pd.read_sql(f"PRAGMA table_info({table});", con)["name"].tolist())

def list_tables(con):
    return pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", con)["name"].tolist()

def count_all(con, table, where_sql="", params=()):
    return int(pd.read_sql(f"SELECT COUNT(*) AS c FROM {table} {where_sql}", con, params=params)["c"].iat[0])

def distinct_count(con, table, col):
    cols = get_columns(con, table)
    if col not in cols: return 0
    return int(pd.read_sql(f"SELECT COUNT(DISTINCT {col}) AS c FROM {table} WHERE {col} IS NOT NULL", con)["c"].iat[0])

def value_list(con, table, col):
    cols = get_columns(con, table)
    if col not in cols: return []
    return pd.read_sql(f"SELECT DISTINCT {col} AS v FROM {table} WHERE {col} IS NOT NULL ORDER BY 1", con)["v"].dropna().tolist()

def make_link(url):
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        return f'<a href="{url}" target="_blank">Open</a>'
    return ""

# =========================
# Pick the working table
# =========================
with sqlite3.connect(DB_PATH) as con:
    tables = list_tables(con)
if "records_norm" in tables:
    TABLE = "records_norm"
elif "records" in tables:
    TABLE = "records"
else:
    st.error("No 'records_norm' or 'records' table found in the database.")
    st.stop()

# Figure out columns & choose defaults
with sqlite3.connect(DB_PATH) as con:
    existing = get_columns(con, TABLE)
    name_col = "name_std" if "name_std" in existing else ("name" if "name" in existing else None)
    city_list = value_list(con, TABLE, "city") if "city" in existing else []
    state_field = "state_std" if "state_std" in existing else ("state" if "state" in existing else None)
    state_list = value_list(con, TABLE, state_field) if state_field else []

# =========================
# UI
# =========================
st.title("Business Directory")
st.markdown('<div class="small-subtle">Fast search & filters on a normalized dataset</div>', unsafe_allow_html=True)

# Sidebar filters
with st.sidebar:
    st.header("Filters")
    kw_fields = [c for c in [name_col, "full_address", "site"] if c and c in existing]
    q = st.text_input("Keyword (name / address / website)")
    city = st.selectbox("City", ["(any)"] + city_list) if city_list else "(any)"
    state = st.selectbox("State", ["(any)"] + state_list) if state_list else "(any)"
    zip_like = st.text_input("ZIP / Postal (starts with)")  # prefix filter
    st.markdown("---")
    page_size = st.number_input("Rows per page", 10, 200, 50, 10)

# Build WHERE
where, params = [], []

if q and kw_fields:
    like_clause = " OR ".join([f"{c} LIKE ?" for c in kw_fields])
    where.append(f"({like_clause})")
    params += [f"%{q}%"] * len(kw_fields)

if "city" in existing and city != "(any)":
    where.append("city = ?"); params.append(city)

if state_field and state != "(any)":
    where.append(f"{state_field} = ?"); params.append(state)

zip_field = "postal_code_std" if "postal_code_std" in existing else ("postal_code" if "postal_code" in existing else None)
if zip_field and zip_like.strip():
    where.append(f"{zip_field} LIKE ?"); params.append(zip_like.strip() + "%")

where_sql = ("WHERE " + " AND ".join(where)) if where else ""

# KPIs
with sqlite3.connect(DB_PATH) as con:
    total_rows    = count_all(con, TABLE)
    filtered_rows = count_all(con, TABLE, where_sql, params)
    n_cities      = distinct_count(con, TABLE, "city")
    n_zips        = distinct_count(con, TABLE, "postal_code_std" if "postal_code_std" in existing else "postal_code")

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f'<div class="kpi"><div class="label">Total Rows</div><div class="value">{total_rows:,}</div></div>', unsafe_allow_html=True)
with c2:
    st.markdown(f'<div class="kpi"><div class="label">Rows (filtered)</div><div class="value">{filtered_rows:,}</div></div>', unsafe_allow_html=True)
with c3:
    st.markdown(f'<div class="kpi"><div class="label">Cities</div><div class="value">{n_cities:,}</div></div>', unsafe_allow_html=True)
with c4:
    st.markdown(f'<div class="kpi"><div class="label">ZIPs (distinct)</div><div class="value">{n_zips:,}</div></div>', unsafe_allow_html=True)

st.divider()

# Pagination (Prev/Next)
if "page" not in st.session_state:
    st.session_state.page = 1
max_page = max(1, (filtered_rows + page_size - 1) // page_size)
if st.session_state.page > max_page: st.session_state.page = max_page
if st.session_state.page < 1: st.session_state.page = 1
offset = (st.session_state.page - 1) * page_size

col_prev, col_info, col_next = st.columns([1,3,1])
with col_prev:
    if st.button("◀ Prev") and st.session_state.page > 1:
        st.session_state.page -= 1
with col_next:
    if st.button("Next ▶") and st.session_state.page < max_page:
        st.session_state.page += 1
with col_info:
    start_row = 0 if filtered_rows == 0 else offset + 1
    end_row   = min(filtered_rows, offset + page_size)
    st.markdown(f"<div class='pager'><span class='info'>Page <b>{st.session_state.page}</b> of <b>{max_page}</b> — showing {start_row}–{end_row} of {filtered_rows}</span></div>", unsafe_allow_html=True)

# Visible columns (prefer name_std; no lat/lng)
select_schema = [
    (("name_std" if "name_std" in existing else "name") if name_col else None, "Name"),
    ("phone", "Phone"),
    ("full_address", "Address"),
    ("city", "City"),
    (state_field, "State") if state_field else (None, None),
    (zip_field, "ZIP") if zip_field else (None, None),
    ("country", "Country"),
    ("location_link", "Map"),
    ("site", "Website"),
]
select_list = [f'{col} AS "{label}"' for col, label in select_schema if col and col in existing]
if not select_list:
    st.error("No expected columns found.")
    st.stop()

order_expr = "COALESCE(name_std, name)" if ("name_std" in existing or "name" in existing) else select_list[0].split(" AS ")[0]

sql = f"""
SELECT {", ".join(select_list)}
FROM {TABLE}
{where_sql}
ORDER BY {order_expr}
LIMIT ? OFFSET ?;
"""
params2 = params + [int(page_size), int(offset)]

with sqlite3.connect(DB_PATH) as con:
    df = pd.read_sql(sql, con, params=params2)

def linkify(df_):
    for col in ["Map", "Website"]:
        if col in df_.columns:
            df_[col] = df_[col].apply(lambda u: f'<a href="{u}" target="_blank">Open</a>' if isinstance(u,str) and u.startswith(("http://","https://")) else "")
    return df_

if not df.empty:
    df = linkify(df.copy())
    st.subheader("Results")
    st.caption("Use sidebar filters. Download the current page or full filtered data below.")
    st.write(df.to_html(escape=False, index=False), unsafe_allow_html=True)

    page_csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download This Page (CSV)", data=page_csv, file_name=f"results_page_{st.session_state.page}.csv", mime="text/csv")

    with sqlite3.connect(DB_PATH) as con:
        full_df = pd.read_sql(f"SELECT {', '.join(select_list)} FROM {TABLE} {where_sql} ORDER BY {order_expr}", con, params=params)
    full_csv = full_df.to_csv(index=False).encode("utf-8")
    st.download_button("Download All Filtered (CSV)", data=full_csv, file_name="results_filtered.csv", mime="text/csv")
else:
    st.info("No results. Adjust filters or keyword.")

# Footer
st.markdown('<div class="footer">Created by Nishant for Gaurav</div>', unsafe_allow_html=True)
