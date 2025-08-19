import time
import pandas as pd
import streamlit as st
from datetime import datetime
from standardbots import StandardBotsRobot

st.set_page_config(page_title="RO1 Live Dashboard", layout="wide")

# --- Inputs ---
st.sidebar.header("Connection")
default_url = st.secrets.get("sb_url", "https://cb2114.sb.app")
default_token = st.secrets.get("sb_token", "")
url = st.sidebar.text_input("Standard Bots URL", default_url, help="e.g., https://xxxxx.sb.app")
token = st.sidebar.text_input("API Token", default_token, type="password")
refresh_s = st.sidebar.slider("Refresh interval (seconds)", 0.5, 5.0, 1.0, 0.5)

st.sidebar.header("Variables to read")
var_names = st.sidebar.text_input(
    "Comma-separated variable names",
    value="speed_rpm,load_pct,at_home",
    help="Use the exact variable names configured on your robot"
)

run = st.sidebar.toggle("Start streaming", value=False)

st.title("RO1 Live (Standard Bots SDK)")
st.caption("Reads robot variables via the Standard Bots Python SDK and displays KPIs and charts.")

# --- Initialize SDK lazily so we can reconnect on changes ---
@st.cache_resource(show_spinner=False)
def get_sdk(_url: str, _token: str):
    return StandardBotsRobot(
        url=_url,
        token=_token,
        robot_kind=StandardBotsRobot.RobotKind.Live,
    )

# --- UI placeholders ---
kpi_cols = st.columns(4)
table_ph = st.empty()
chart_ph = st.empty()
status_ph = st.empty()

# Maintain history for charting
if "hist" not in st.session_state:
    st.session_state.hist = pd.DataFrame(columns=["ts"])

def append_sample(sample: dict):
    row = {"ts": datetime.utcnow()}
    row.update(sample)
    st.session_state.hist = pd.concat([st.session_state.hist, pd.DataFrame([row])], ignore_index=True)
    # keep last ~300 points
    if len(st.session_state.hist) > 300:
        st.session_state.hist = st.session_state.hist.iloc[-300:].reset_index(drop=True)

def safe_metric(col, label, value):
    try:
        if isinstance(value, (int, float)):
            col.metric(label, f"{value}")
        else:
            col.metric(label, str(value))
    except Exception:
        col.metric(label, "—")

# --- Streaming loop ---
if run:
    # Basic input validation
    if not url or not token:
        status_ph.error("Please provide URL and API token.")
        st.stop()

    names = [v.strip() for v in var_names.split(",") if v.strip()]
    if not names:
        status_ph.error("Please provide at least one variable name.")
        st.stop()

    sdk = get_sdk(url, token)

    # Open/refresh connection each tick inside a context manager
    while run:
        sample = {}
        try:
            with sdk.connection():
                # Read variables
                for name in names:
                    try:
                        sample[name] = sdk.variables.get(name)
                    except Exception as e:
                        sample[name] = None
                # lightweight status call (optional; comment out if not needed)
                # state = sdk.status()  # dict-like; you can display pieces if you want
                status_ph.success(f"Connected to {url} · {datetime.utcnow().strftime('%H:%M:%S')} UTC")
        except Exception as e:
            status_ph.error(f"Connection/read error: {e}")
            # brief backoff before retry
            time.sleep(min(refresh_s, 2.0))
            # re-check toggle and continue loop
            run = st.session_state.get("Start streaming", False)
            continue

        # Update KPIs (first four variables)
        labels = names[:4]
        for i, label in enumerate(labels):
            safe_metric(kpi_cols[i], label, sample.get(label))

        # Table
        table_ph.dataframe(pd.DataFrame.from_dict(sample, orient="index", columns=["value"]))

        # Chart (only numeric columns)
        append_sample(sample)
        df = st.session_state.hist.copy()
        df = df.set_index("ts")
        num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if num_cols:
            chart_ph.line_chart(df[num_cols])

        # Sleep + check toggle again
        time.sleep(refresh_s)
        run = st.session_state.get("Start streaming", False)

else:
    status_ph.info("Toggle ‘Start streaming’ in the sidebar to begin reading variables.")
    st.write("Tips:")
    st.markdown(
        "- Make sure your token has permission to read the variables you list\n"
        "- Use exact variable names as configured on your robot\n"
        "- Adjust the refresh interval to balance responsiveness vs. load"
    )
