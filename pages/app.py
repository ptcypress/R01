# pip install streamlit standardbots pandas
import time, pandas as pd, streamlit as st
from datetime import datetime
from standardbots import StandardBotsRobot

st.set_page_config(page_title="RO1 Live (SDK Variables)", layout="wide")

url   = st.sidebar.text_input("SB URL", "https://cb2114.sb.app")
token = st.sidebar.text_input("API Token", type="password")
vars_csv = st.sidebar.text_input("Variables (comma-separated)", "speed_rpm,load_pct,at_home")
refresh = st.sidebar.slider("Refresh (s)", 0.5, 5.0, 1.0, 0.5)
go = st.sidebar.toggle("Start", value=False)

@st.cache_resource
def get_robot(u,t):
    return StandardBotsRobot(url=u, token=t, robot_kind=StandardBotsRobot.RobotKind.Live)

def resolve_methods(vc):
    def _list():
        return vc.load()

    def _get(var):
        items = vc.load()
        match = next((v for v in items if v.get("name") == var), None)
        return match.get("value") if match else None

    def _set(var, value):
        items = vc.load()
        match = next((v for v in items if v.get("name") == var), None)
        if not match:
            raise ValueError(f"Variable {var} not found")
        return vc.update(id=match["id"], value=value)

    return _list, _get, _set

status = st.empty(); k1,k2,k3,k4 = st.columns(4); table = st.empty(); chart = st.empty()

if "hist" not in st.session_state:
    st.session_state.hist = pd.DataFrame(columns=["ts"])

def append_hist(sample):
    row = {"ts": datetime.utcnow(), **sample}
    st.session_state.hist = pd.concat([st.session_state.hist, pd.DataFrame([row])], ignore_index=True).tail(300)

if go:
    if not url or not token:
        status.error("Enter URL and token, then toggle Start."); st.stop()

    robot = get_robot(url, token)
    names = [v.strip() for v in vars_csv.split(",") if v.strip()]

    vc = robot.routine_editor.variables
    list_vars, get_var, set_var = resolve_methods(vc)

    while go:
        sample = {}
        try:
            with robot.connection():
                for n in names:
                    try:
                        sample[n] = get_var(n)
                    except Exception:
                        sample[n] = None
                status.success("Connected")
        except Exception as e:
            status.error(f"SDK error: {e}")
            time.sleep(min(2.0, refresh))
            go = st.session_state.get("Start", False)
            continue

        for col, label in zip([k1,k2,k3,k4], names[:4]):
            col.metric(label, "-" if sample.get(label) is None else str(sample.get(label)))

        table.dataframe(pd.DataFrame.from_dict(sample, orient="index", columns=["value"]))

        append_hist(sample)
        df = st.session_state.hist.set_index("ts")
        num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        if num_cols: chart.line_chart(df[num_cols])

        time.sleep(refresh)
        go = st.session_state.get("Start", False)
else:
    status.info("Fill URL/token, list your variable names, then toggle Start.")
