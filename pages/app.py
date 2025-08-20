# streamlit_sb_ok_demo.py (corrected for RobotKind.Live)

import time
import json
import inspect
from functools import reduce

import streamlit as st
import dataclasses
from enum import Enum
from types import FunctionType, MethodType

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
    # Add more verified endpoints here after you test them
]

st.markdown("#### Choose an SDK endpoint")
colA, colB = st.columns([2, 1])
endpoint = colA.selectbox("Method path (dot notation)", PRESETS, index=0)
endpoint = colA.text_input("…or type a method path",
                           value=st.session_state.get("endpoint_input", endpoint),
                           key="endpoint_input",
                           help="Example: movement.brakes.get_brakes_state")

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

# --- Method discovery UI ---
with st.sidebar:
    if st.button("🔎 Discover methods (depth 2)"):
        with st.spinner("Scanning SDK object graph…"):
            with sdk.connection():
                methods = _discover_methods(sdk, max_depth=2)
        st.session_state["discovered_methods"] = methods

if "discovered_methods" in st.session_state:
    methods = st.session_state["discovered_methods"]
    with st.expander(f"Discovered methods ({len(methods)})", expanded=False):
        options = [m["path"] for m in methods]
        pick = st.selectbox("Pick a method", options, key="pick_discovered")
        sig = next((m["signature"] for m in methods if m["path"] == pick), "(…)")
        st.code(f"{pick}{sig}")
        if st.button("Use selected"):
            st.session_state["endpoint_input"] = pick
            # Trigger a rerun to propagate into the text input
            if hasattr(st, "rerun"):
                st.rerun()
            elif hasattr(st, "experimental_rerun"):
                st.experimental_rerun()

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

# JSON-safe serialization helpers (avoid st.json errors when SDK returns models/enums)
def _to_jsonable(obj):
    try:
        if hasattr(obj, "model_dump") and callable(obj.model_dump):
            return obj.model_dump()
        if hasattr(obj, "dict") and callable(obj.dict):
            return obj.dict()
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, (bytes, bytearray)):
            return obj.decode(errors="replace")
        json.dumps(obj)
        return obj
    except TypeError:
        return {"value": str(obj)}

# Method discovery (depth-limited, safe)
def _sig_str(fn):
    try:
        return str(inspect.signature(fn))
    except Exception:
        return "(…)"

def _discover_methods(root, max_depth: int = 2):
    seen = set()
    results = []
    def walk(obj, path: str, depth: int):
        if depth > max_depth:
            return
        try:
            names = [n for n in dir(obj) if not n.startswith("_")]
        except Exception:
            return
        for n in names:
            try:
                child = getattr(obj, n)
            except Exception:
                continue
            full = f"{path}.{n}" if path else n
            if callable(child):
                results.append({"path": full, "signature": _sig_str(child)})
                continue
            if isinstance(child, (str, bytes, bytearray, int, float, bool, dict, list, tuple, Enum)):
                continue
            oid = id(child)
            if oid in seen:
                continue
            seen.add(oid)
            walk(child, full, depth + 1)
    walk(root, "", 0)
    results.sort(key=lambda r: r["path"])
    return results

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
            _data = _to_jsonable(res["data"])
            try:
                st.json(_data)
            except Exception:
                st.write(_data)
        else:
            status = res.get("status")
            result_slot.error(f"❌ {endpoint} failed (status={status})")
            _raw = _to_jsonable(res["raw"])
            try:
                raw_slot.json(_raw)
            except Exception:
                raw_slot.write(_raw)

# First call
run_once()

# Gentle auto-refresh without an infinite loop (avoids locking the runner)
# Streamlit >=1.29 uses st.rerun(); older versions used st.experimental_rerun().
def _safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()

if auto_refresh:
    time.sleep(refresh_sec)
    _safe_rerun()
