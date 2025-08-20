# streamlit_sb_ok_demo.py

import time
import json
import inspect
from functools import reduce

import streamlit as st
from standardbots import StandardBotsRobot, api  # api imported for enums/types if needed

st.set_page_config(page_title="Standard Bots – Live Reader (.ok())", layout="wide")

# --- Sidebar auth/config ---
default_url   = st.secrets.get("sb_url", "https://<your-workspace>.sb.app")
default_token = st.secrets.get("sb_token", "")

st.sidebar.markdown("### Connection")
url   = st.sidebar.text_input("Workspace URL", default_url)
token = st.sidebar.text_input("API Token", default_token, type="password")

robot_kind = st.sidebar.selectbox(
    "Robot kind",
    options=[StandardBotsRobot.RobotKind.Simulated, StandardBotsRobot.RobotKind.Real],
    index=0,
    format_func=lambda k: "Simulated" if k == StandardBotsRobot.RobotKind.Simulated else "Real",
)

refresh_sec = st.sidebar.number_input("Refresh interval (sec)", 1, 30, 3)
auto_refresh = st.sidebar.checkbox("Auto-refresh", True)

st.title("Standard Bots – Methods • Models • Responses")
st.caption("Calls SDK endpoints and unwraps with `.ok()` to show real values.")

# Common presets you can extend
PRESETS = [
    "movement.brakes.get_brakes_state",
    "equipment.get_gripper_configuration",
    "system.get_status",            # if present in your SDK
    "diagnostics.get_health",       # if present in your SDK
]
st.markdown("#### Choose an SDK endpoint")
colA, colB = st.columns([2, 1])
endpoint = colA.selectbox("Method path (dot notation)", PRESETS, index=0)
endpoint = colA.text_input("…or type a method path", value=endpoint, help="Example: movement.brakes.get_brakes_state")

# Optional kwargs as JSON
kwargs_text = colB.text_area("Method kwargs (JSON)", value="{}", height=100, help='e.g. {"axis":"x"} if the method takes parameters')
try:
    call_kwargs = json.loads(kwargs_text) if kwargs_text.strip() else {}
except Exception as e:
    st.error(f"Invalid kwargs JSON: {e}")
    call_kwargs = {}

# --- SDK init ---
sdk = StandardBotsRobot(
    url=url,
    token=token,
    robot_kind=robot_kind,
)

# Utility: resolve dotted attribute path on sdk (e.g., "movement.brakes.get_brakes_state")
def resolve_method(root, dotted):
    try:
        parts = dotted.split(".")
        obj = reduce(getattr, parts, root)
        if not callable(obj):
            raise AttributeError(f"Resolved object is not callable: {dotted}")
        return obj
    except Exception as e:
        raise RuntimeError(f"Could not resolve method '{dotted}': {e}")

# Call helper that uses .ok() unwrapping; falls back to raw on error
def call_ok_unwrap(method, **kwargs):
    resp = method(**kwargs)
    # Try the happy path: unwrap with ok()
    try:
        data = resp.ok()  # <- per docs: asserts 200 and returns unwrapped data
        return {"success": True, "data": data, "status": 200, "raw": None}
    except Exception as unwarp_error:
        # Fall back to raw fields for debugging
        status = getattr(resp, "status", None)
        raw = {
            "status": status,
            "data": getattr(resp, "data", None),
            "error": str(unwarp_error),
        }
        return {"success": False, "data": None, "status": status, "raw": raw}

result_slot = st.empty()
raw_slot = st.expander("Raw / Debug", expanded=False)

def run_once():
    with sdk.connection():
        try:
            method = resolve_method(sdk, endpoint)
        except RuntimeError as e:
            result_slot.error(str(e))
            return

        # Introspect signature to help the user (optional)
        try:
            sig = inspect.signature(method)
            st.caption(f"Signature: `{endpoint}{sig}`")
        except Exception:
            pass

        res = call_ok_unwrap(method, **call_kwargs)

        if res["success"]:
            result_slot.success(f"✅ {endpoint} → 200 OK")
            # Show unpacked values cleanly
            st.json(res["data"])
        else:
            result_slot.error(f"❌ {endpoint} failed (status={res['status']})")
            raw_slot.write(res["raw"])

# First call
run_once()

# Polling loop (no flicker; updates in place)
if auto_refresh:
    while True:
        time.sleep(refresh_sec)
        run_once()
