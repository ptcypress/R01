# streamlit_sb_ok_demo.py (corrected for RobotKind.Live)

import time
import json
import inspect
from functools import reduce

import streamlit as st

try:
    from standardbots import StandardBotsRobot, models  # models optional
except Exception as e:
    st.error("Failed to import 'standardbots'. Install it in your environment.\n" \
            "+ Tip: pip install --no-cache-dir standardbots\n" \
            f"Import error: {e}")
    st.stop()

st.set_page_config(page_title="Standard Bots – Live Reader (.ok())", layout="wide")

# --- Sidebar auth/config ---
default_url   = st.secrets.get("sb_url", "https://<your-workspace>.sb.app")
default_token = st.secrets.get("sb_token", "")

st.sidebar.markdown("### Connection")
url   = st.sidebar.text_input("Workspace URL", default_url)
token = st.sidebar.text_input("API Token", default_token, type="password")

# --- Robot kind selection (robust across SDK versions) ---
RK = StandardBotsRobot.RobotKind
try:
    rk_members = list(RK)
except Exception:
    rk_members = [RK.Simulated]

preferred = ("live", "real")
default_index = 0
for i, m in enumerate(rk_members):
    name = getattr(m, "name", str(m)).lower()
    if name in preferred:
        default_index = i
        break

robot_kind = st.sidebar.selectbox(
    "Robot kind",
    options=rk_members,
    index=default_index,
    format_func=lambda m: getattr(m, "name", str(m)).capitalize(),
)

refresh_sec  = st.sidebar.number_input("Refresh interval (sec)", 1, 60, 3)
auto_refresh = st.sidebar.checkbox("Auto-refresh", True)

st.title("Standard Bots – Methods • Models • Responses")
st.caption("Calls SDK endpoints and unwraps with `.ok()` to show real values.")

# Common presets you can extend (keep only ones that exist in your SDK)
PRESETS = [
    "movement.brakes.get_brakes_state",
    "equipment.get_gripper_configuration",
    "system.get_status",
    "diagnostics.get_health",
]

st.markdown("#### Choose an SDK endpoint")
colA, colB = st.columns([2, 1])
endpoint = colA.selectbox("Method path (dot notation)", PRESETS, index=0)
endpoint = colA.text_input("…or type a method path", value=endpoint, help="Example: movement.brakes.get_brakes_state")

# Optional kwargs as JSON
kwargs_text = colB.text_area("Method kwargs (JSON)", value="{}", height=110,
                             help='e.g. {"axis":"x"} if the method takes parameters')
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
def resolve_method(root, dotted: str):
    try:
        parts = [p for p in dotted.split(".") if p]
        obj = reduce(getattr, parts, root)
        if not callable(obj):
            raise RuntimeError(f"Resolved object is not callable: {dotted}")
        return obj
    except Exception as e:
        raise RuntimeError(f"Could not resolve method '{dotted}': {e}")

# Call helper that uses .ok() unwrapping; falls back to raw on error
def call_ok_unwrap(method, **kwargs):
    resp = method(**kwargs)
    # Try the happy path: unwrap with ok()
    try:
        data = resp.ok()  # asserts 200 & returns unwrapped data
        return {"success": True, "data": data, "status": 200, "raw": None}
    except Exception as e:
        return {
            "success": False,
            "data": None,
            "status": getattr(resp, "status", None),
            "raw": {
                "status": getattr(resp, "status", None),
                "data": getattr(resp, "data", None),
                "error": str(e),
            },
        }

# UI slots
result_slot = st.empty()
raw_slot = st.expander("Raw / Debug", expanded=False)

# Optional: show SDK version & enum members
try:
    import standardbots as _sb
    st.sidebar.caption(f"SDK version: {getattr(_sb, '__version__', 'unknown')}")
    st.sidebar.caption("RobotKind options: " + ", ".join(getattr(m, 'name', str(m)) for m in rk_members))
except Exception:
    pass


def run_once():
    with sdk.connection():
        try:
            method = resolve_method(sdk, endpoint)
        except Exception as e:
            result_slot.error(str(e))
            return

        # Introspect signature (best effort)
        try:
            sig = inspect.signature(method)
            st.caption(f"Signature: `{endpoint}{sig}`")
        except Exception:
            pass

        res = call_ok_unwrap(method, **call_kwargs)
        if res["success"]:
            result_slot.success(f"✅ {endpoint} → 200 OK")
            st.json(res["data"])
        else:
            status = res.get("status")
            result_slot.error(f"❌ {endpoint} failed (status={status})")
            raw_slot.write(res["raw"])

# First call
run_once()

# Gentle auto-refresh without an infinite loop (avoids locking the runner)
if auto_refresh:
    time.sleep(refresh_sec)
    st.experimental_rerun()
