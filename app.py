import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="Infografis Prakiraan Cuaca + QAM Simulasi", layout="wide")

API_BASE = "https://cuaca.bmkg.go.id/api/df/v1/forecast/adm"

@st.cache_data(ttl=300)
def fetch_forecast(adm1: str):
    params = {"adm1": adm1}
    resp = requests.get(API_BASE, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()

def flatten_cuaca_entry(entry):
    rows = []
    lokasi = entry.get("lokasi", {})
    for group in entry.get("cuaca", []):
        for obs in group:
            r = obs.copy()
            # metadata lokasi
            r.update({
                "adm1": lokasi.get("adm1"),
                "adm2": lokasi.get("adm2"),
                "provinsi": lokasi.get("provinsi"),
                "kotkab": lokasi.get("kotkab"),
                "lon": lokasi.get("lon"),
                "lat": lokasi.get("lat"),
                "timezone": lokasi.get("timezone", "+0700"),
                "type": lokasi.get("type"),
            })
            # parse datetime
            try:
                r["utc_datetime_dt"] = pd.to_datetime(r.get("utc_datetime"))
            except:
                r["utc_datetime_dt"] = pd.NaT
            try:
                r["local_datetime_dt"] = pd.to_datetime(r.get("local_datetime"))
            except:
                r["local_datetime_dt"] = pd.NaT
            rows.append(r)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # numeric
    numeric_cols = ["t", "tcc", "tp", "wd_deg", "ws", "hu", "vs"]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def simulate_qam_from_forecast(df: pd.DataFrame):
    """
    Simulasikan QAM dari data prakiraan (ambil yang paling mendekati waktu sekarang).
    Kembalikan dict / row dengan kolom-kolom QAM.
    """
    if df.empty:
        return None
    # cari baris paling dekat ke waktu sekarang (local)
    # asumsi df["local_datetime_dt"] ada
    now = pd.Timestamp.now(tz=None)
    # hitung selisih absolut
    df = df.copy()
    df["delta"] = df["local_datetime_dt"].apply(lambda x: abs((x - now).total_seconds()) if pd.notna(x) else float("inf"))
    df = df.sort_values("delta")
    rec = df.iloc[0]
    # buat dict QAM
    q = {
        "Waktu (lokal)": rec.get("local_datetime_dt", ""),
        "Arah angin (deg)": rec.get("wd_deg", "—"),
        "Kecepatan angin (m/s)": rec.get("ws", "—"),
        "Tutupan awan (%)": rec.get("tcc", "—"),
        "Curah hujan (mm)": rec.get("tp", "—"),
        "Suhu (°C)": rec.get("t", "—"),
        "Kelembaban (%)": rec.get("hu", "—"),
        "Visibilitas (asi)": rec.get("vs", "—"),  # vs = visibility in some unit
        # tekanan mungkin tidak tersedia dalam forecast API
        "Tekanan": rec.get("pressure", "—") if "pressure" in rec else "—"
    }
    return q

# Sidebar
st.sidebar.title("Kontrol Infografis + QAM Simulasi")
adm1 = st.sidebar.text_input("Kode ADM1 (provinsi)", value="32")
refresh = st.sidebar.button("Ambil ulang data")

show_map = st.sidebar.checkbox("Tampilkan peta lokasi", value=True)
show_table = st.sidebar.checkbox("Tampilkan tabel data", value=False)
show_qam = st.sidebar.checkbox("Tampilkan QAM Simulasi", value=True)

st.sidebar.markdown("---")
start_max = None  # nanti diisi

# Main UI
st.title("Infografis Prakiraan Cuaca & QAM Simulasi (BMKG)")
st.markdown("Sumber: `https://cuaca.bmkg.go.id/api/df/v1/forecast/adm?adm1=<kode>`")

# ambil data
with st.spinner("Mengambil data..."):
    try:
        raw = fetch_forecast(adm1)
    except Exception as e:
        st.error(f"Gagal mengambil data: {e}")
        st.stop()

lokasi_meta = raw.get("lokasi", {})
entries = raw.get("data", [])
if not entries:
    st.warning("Tidak ada data untuk ADM1 ini.")
    st.stop()

# mapping lokasi
mapping = {}
for e in entries:
    lok = e.get("lokasi", {})
    label = lok.get("kotkab") or lok.get("adm2") or f"Lokasi {len(mapping)+1}"
    key = lok.get("adm2") or lok.get("kotkab") or str(len(mapping)+1)
    mapping[label] = {"key": key, "entry": e}

col1, col2 = st.columns([2, 1])
with col1:
    prov_name = lokasi_meta.get("provinsi", "—")
    st.subheader(f"Provinsi: {prov_name}")
    loc_choice = st.selectbox("Pilih lokasi (Kabupaten/Kota)", options=list(mapping.keys()))
with col2:
    st.metric("Jumlah lokasi tersedia", len(mapping))

selected_entry = mapping[loc_choice]["entry"]
df = flatten_cuaca_entry(selected_entry)
if df.empty:
    st.warning("Data cuaca kosong.")
    st.stop()

df = df.sort_values(by="utc_datetime_dt")
min_dt = df["local_datetime_dt"].min()
max_dt = df["local_datetime_dt"].max()
if hasattr(min_dt, "to_pydatetime"):
    min_dt = min_dt.to_pydatetime()
if hasattr(max_dt, "to_pydatetime"):
    max_dt = max_dt.to_pydatetime()

st.sidebar.markdown("---")
start_dt = st.sidebar.slider(
    "Rentang waktu (lokal)",
    min_value=min_dt,
    max_value=max_dt,
    value=(min_dt, max_dt),
    format="DD-MM-YYYY HH:mm"
)

mask = (df["local_datetime_dt"] >= pd.to_datetime(start_dt[0])) & (df["local_datetime_dt"] <= pd.to_datetime(start_dt[1]))
df_sel = df.loc[mask].copy()

# Tampilkan QAM Simulasi jika dipilih
if show_qam:
    st.markdown("---")
    st.header("QAM Simulasi")
    q = simulate_qam_from_forecast(df_sel)
    if q is None:
        st.info("Tidak dapat membuat QAM simulasi (data kosong).")
    else:
        # Tampilkan sebagai tabel satu baris
        df_q = pd.DataFrame([q])
        # format kolom waktu sebagai string
        if isinstance(q["Waktu (lokal)"], pd.Timestamp):
            df_q["Waktu (lokal)"] = df_q["Waktu (lokal)"].dt.strftime("%d %b %Y %H:%M")
        st.table(df_q)

# Tampilkan metrik top
r1c1, r1c2, r1c3, r1c4 = st.columns(4)
now_row = df_sel.iloc[0] if not df_sel.empty else df.iloc[0]
with r1c1:
    st.metric("Suhu (°C)", f"{now_row.get('t', '—')}")
with r1c2:
    st.metric("Kelembaban (%)", f"{now_row.get('hu', '—')}")
with r1c3:
    st.metric("Kecepatan Angin (m/s)", f"{now_row.get('ws', '—')}")
with r1c4:
    st.metric("Awan & Curah", f"Cloud cover: {now_row.get('tcc', '—')}%, TP: {now_row.get('tp', '—')} mm")

# Grafik tren
st.markdown("---")
st.header("Grafik Tren — Parameter Utama")
if df_sel.empty:
    st.warning("Tidak ada data di rentang waktu yang dipilih.")
else:
    fig_t = px.line(df_sel, x="local_datetime_dt", y="t", markers=True, title="Suhu (°C)")
    fig_t.update_layout(yaxis_title="Temperature (°C)", xaxis_title="Waktu (Lokal)")
    fig_hu = px.line(df_sel, x="local_datetime_dt", y="hu", markers=True, title="Kelembaban (%)")
    fig_hu.update_layout(yaxis_title="Rel Humidity (%)", xaxis_title="Waktu (Lokal)")
    fig_ws = px.line(df_sel, x="local_datetime_dt", y="ws", markers=True, title="Kecepatan Angin (m/s)")
    fig_ws.update_layout(yaxis_title="Wind Speed (m/s)", xaxis_title="Waktu (Lokal)")
    fig_tp = px.bar(df_sel, x="local_datetime_dt", y="tp", title="Curah Hujan (mm)")
    fig_tp.update_layout(yaxis_title="Rainfall (mm)", xaxis_title="Waktu (Lokal)")

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(fig_t, use_container_width=True)
        st.plotly_chart(fig_hu, use_container_width=True)
    with c2:
        st.plotly_chart(fig_ws, use_container_width=True)
        st.plotly_chart(fig_tp, use_container_width=True)

# Timeline cuaca ringkas
st.markdown("---")
st.header("Tabel Cuaca (Ringkas)")
timeline = df_sel.sort_values(by="local_datetime_dt")[
    ["local_datetime_dt", "weather_desc", "t", "hu", "ws", "tp", "image"]
].copy()
timeline["Waktu (Lokal)"] = timeline["local_datetime_dt"].dt.strftime("%d %b %Y %H:%M")
timeline["Suhu (°C)"] = timeline["t"].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")
timeline["Kelembaban (%)"] = timeline["hu"].apply(lambda x: f"{x:.0f}" if pd.notna(x) else "—")
timeline["Kecepatan Angin (m/s)"] = timeline["ws"].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")
timeline["Curah Hujan (mm)"] = timeline["tp"].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")
timeline["Cuaca"] = timeline.apply(
    lambda r: f"<img src='{r['image']}' width='36' height='36' style='vertical-align:middle;margin-right:6px;'/> {r['weather_desc']}",
    axis=1
)
cols_show = ["Waktu (Lokal)", "Cuaca", "Suhu (°C)", "Kelembaban (%)", "Kecepatan Angin (m/s)", "Curah Hujan (mm)"]
timeline_show = timeline[cols_show]
table_html = """
<style>
table.weather-table {
  border-collapse: collapse;
  width: 100%;
  font-size: 14px;
}
table.weather-table th {
  background-color: #1e88e5;
  color: white;
  text-align: center;
  padding: 8px;
}
table.weather-table td {
  border-bottom: 1px solid #ddd;
  padding: 6px 8px;
  text-align: center;
}
table.weather-table tr:hover {
  background-color: #f1f5fb;
}
</style>
<table class='weather-table'>
<thead><tr>""" + "".join([f"<th>{c}</th>" for c in cols_show]) + "</tr></thead><tbody>"""
for _, r in timeline_show.iterrows():
    table_html += "<tr>" + "".join([f"<td>{r[c]}</td>" for c in cols_show]) + "</tr>"
table_html += "</tbody></table>"
st.markdown(table_html, unsafe_allow_html=True)

# Map
if show_map:
    st.markdown("---")
    st.header("Peta Lokasi")
    try:
        lat = float(selected_entry.get("lokasi", {}).get("lat", 0))
        lon = float(selected_entry.get("lokasi", {}).get("lon", 0))
        map_df = pd.DataFrame({"lat": [lat], "lon": [lon]})
        st.map(map_df)
    except Exception as e:
        st.warning(f"Peta tidak tersedia: {e}")

# Raw table
if show_table:
    st.markdown("---")
    st.header("Tabel Data (Mentah)")
    st.dataframe(df_sel)

# Export
st.markdown("---")
st.header("Ekspor Data")
csv = df_sel.to_csv(index=False)
json_text = df_sel.to_json(orient="records", force_ascii=False, date_format="iso")
col_dl1, col_dl2 = st.columns(2)
with col_dl1:
    st.download_button("Unduh CSV", data=csv, file_name=f"forecast_adm1_{adm1}_{loc_choice}.csv", mime="text/csv")
with col_dl2:
    st.download_button("Unduh JSON", data=json_text, file_name=f"forecast_adm1_{adm1}_{loc_choice}.json", mime="application/json")

st.markdown("""
---
**Catatan:**
- QAM Simulasi ini **bukan data observasi** — hanya interpretasi dari data prakiraan BMKG.
- Beberapa kolom (tekanan, visibilitas, dll) mungkin tidak tersedia di API prakiraan.
- Pilih rentang waktu yang mencakup waktu sekarang agar simulasi lebih relevan.
""")
st.caption("Aplikasi dengan QAM simulasi berdasarkan data prakiraan cuaca — sumber: BMKG")
