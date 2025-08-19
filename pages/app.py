# file: app.py
# pip install streamlit standardbots pandas

import time
import pandas as pd
import streamlit as st
from datetime import datetime
from standardbots import StandardBotsRobot

st.set_page_config(page_title="RO1 Live (Standard Bots SDK)", layout="wide")

# --- Sidebar inputs ---
default_url   = st.secrets.get("sb_url", "https://cb2114.sb.app")
default_token = st.secrets.get("sb_token", "")
url   = st.sidebar.text_input("Workspace URL", default_url, help="e.g., https://<workspace>.sb.app")
token = st.sidebar.text_input("API Token", default_token, type="password")
vars_csv = st.sidebar.text_input("Variables (comma-separated)", "speed_rpm,load_pct,at_home")
refresh = st.sidebar.slider("Refresh interval (s)", 0.5, 5.0, 1.0, 0.5)
run     = st.sidebar.toggle("Start streaming", value=False)

st.title("RO1 Live via Standard Bots SDK")
status_ph = st.empty()
k1, k2, k3, k4 = st.columns(4)
table_ph = st.empty()
chart_ph = st.empty()

@st.cache_resource(show_spinner=False)
def get_robot(u, t):
    return StandardBotsRobot(url=u, token=t, robot_kind=StandardBotsRobot.RobotKind.Live)

if "hist" not in st.session_state:
    st.session_state.hist = pd.DataFrame(columns=["ts"])

def append_hist(sample: dict):
    row = {"ts": datetime.utcnow(), **sample}
    st.session_state.hist = pd.concat([st.session_state.hist, pd.DataFrame([row])], ignore_index=True)
    if len(st.session_state.hist) > 300:
        st.session_state.hist = st.session_state.hist.tail(300).reset_index(drop=True)

def read_by_name(vc, name: str):
    """Read a variable *by name* using vc.load() since no direct getter exists."""
    items = vc.load() or []
    match = next((v for v in items if v.get("name") == name), None)
    return match.get("value") if match else None

def write_by_name(vc, name: str, value):
    """Write a variable by name using vc.update(id=..., value=...)."""
    items = vc.load() or []
    match = next((v for v in items if v.get("name") == name), None)
    if not match:
        raise ValueError(f"Variable '{name}' not found")
    return vc.update(id=match["id"], value=value)

if run:
    if not url or not token:
        status_ph.error("Enter URL and API token, then toggle Start.")
        st.stop()

    robot = get_robot(url, token)
    names = [v.strip() for v in vars_csv.split(",") if v.strip()]

    while run:
        sample = {}
        try:
            with robot.connection():
                # Optional: also surface basic status
                s = robot.status
                status_ph.success(
                    f"Connected · Mode={getattr(s.control, 'mode', None)} · "
                    f"EStop={getattr(s.control, 'estop', None)}"
                )

                vc = robot.routine_editor.variables

                # Read each variable via load()+filter
                for n in names:
                    try:
                        sample[n] = read_by_name(vc, n)
                    except Exception:
                        sample[n] = None

                # (Optional) Example write control in UI:
                # if st.button("Set speed_rpm to 1200"):
                #     write_by_name(vc, "speed_rpm", 1200)

        except Exception as e:
            status_ph.error(f"SDK error: {e}")
            time.sleep(min(2.0, refresh))
            run = st.session_state.get("Start streaming", False)
            continue

        # KPIs (first four)
        for col, label in zip([k1, k2, k3, k4], names[:4]):
            val = sample.get(label)
            col.metric(label, "-" if val is None else str(val))

        # Table of all requested variables
        table_ph.dataframe(pd.DataFrame.from_dict(sample, orient="index", columns=["value"]))

        # Chart numeric variables over time
        append_hist(sample)
        df = st.session_state.hist.set_index("ts")
        num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if num_cols:
            chart_ph.line_chart(df[num_cols])

        time.sleep(refresh)
        run = st.session_state.get("Start streaming", False)
else:
    status_ph.info("Fill URL/token, list your variable names, then toggle Start. "
                   "This uses the SDK via your *.sb.app workspace (no LAN REST/Modbus needed).")
