# streamlit_sb_ok_demo.py — unified rewrite with method discovery, JSON-safe rendering,
# robust RobotKind selection, and smoother auto-refresh.

import json
import time
import inspect
import dataclasses
from enum import Enum
from functools import reduce

import streamlit as st

# ---- Optional: import models for typing / enums if you need them later
try:
    from standardbots import StandardBotsRobot, models  # noqa: F401
except Exception as e:
    st.error("""Failed to import 'standardbots'. Install it first.
Tip: pip install --no-cache-dir standardbots
Import error: {}""".format(e))
    st.stop()

st.set_page_config(page_title="Standard Bots – Live Reader (.ok())", layout="wide")

# =====================================================================================
# Helpers
# =====================================================================================

def _to_jsonable(obj):
    """Convert SDK returns (pydantic models, dataclasses, enums, bytes, etc.)
    into JSON-renderable Python primitives for st.json()."""
    try:
        # pydantic v2
        if hasattr(obj, "model_dump") and callable(obj.model_dump):
            return obj.model_dump()
        # pydantic v1
        if hasattr(obj, "dict") and callable(obj.dict):
            return obj.dict()
        # dataclass
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        # enum
        if isinstance(obj, Enum):
            return obj.value
        # bytes
        if isinstance(obj, (bytes, bytearray)):
            return obj.decode(errors="replace")
        # containers / primitives
        json.dumps(obj)  # probe serializability
        return obj
    except TypeError:
        # last-resort fallback
        return {"value": str(obj)}


def _sig_str(fn):
    try:
        return str(inspect.signature(fn))
    except Exception:
        return "(...)"


def _discover_methods(root, max_depth: int = 2):
    """Walk the SDK object graph and list dotted callables up to max_depth.
    Does not CALL any methods; just discovers attribute paths."""
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
            # Skip obvious data types
            if isinstance(child, (str, bytes, bytearray, int, float, bool, dict, list, tuple, Enum)):
                continue
            oid = id(child)
            if oid in seen:
                continue
            seen.add(oid)
            walk(child, full, depth + 1)

    walk(root, "", 0)
    results.sort(key=lambda r: r["path"])  # stable sort for UI
    return results


def _resolve_method(root, dotted: str):
    """Resolve dotted attribute path on the SDK root; ensure it is callable."""
    try:
        parts = [p for p in dotted.split(".") if p]
        obj = reduce(getattr, parts, root)
        if not callable(obj):
            raise RuntimeError(f"Resolved object is not callable: {dotted}")
        return obj
    except Exception as e:
        raise RuntimeError(f"Could not resolve method '{dotted}': {e}")


def _call_ok_unwrap(method, **kwargs):
    """Invoke SDK method and unwrap via .ok(). On failure, return debug info.
    Handles two failure stages:
      1) invocation errors before a Response exists (bad/missing kwargs)
      2) non-200 responses when calling .ok()
    """
    try:
        resp = method(**kwargs)
    except Exception as e:
        # Method invocation failed before a Response object was created
        import traceback as _tb
        return {
            "success": False,
            "data": None,
            "status": None,
            "raw": {
                "stage": "invoke",
                "error": str(e),
                "trace": _tb.format_exc(),
            },
        }
    try:
        data = resp.ok()  # asserts 200 & returns unwrapped payload
        return {"success": True, "data": data, "status": 200, "raw": None}
    except Exception as e:
        return {
            "success": False,
            "data": None,
            "status": getattr(resp, "status", None),
            "raw": {
                "stage": "ok_unwrap",
                "status": getattr(resp, "status", None),
                "data": getattr(resp, "data", None),
                "error": str(e),
            },
        }


def _safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()

):
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()

# =====================================================================================
# Sidebar: connection + robot kind + refresh + discovery
# =====================================================================================

st.sidebar.markdown("### Connection")
DEFAULT_URL = st.secrets.get("sb_url", "https://<your-workspace>.sb.app")
DEFAULT_TOKEN = st.secrets.get("sb_token", "")
url = st.sidebar.text_input("Workspace URL", DEFAULT_URL)
token = st.sidebar.text_input("API Token", DEFAULT_TOKEN, type="password")

# Robust RobotKind selection across SDK versions (Live vs Real etc.)
RK = StandardBotsRobot.RobotKind
rk_members = list(RK)
preferred = ("live", "real")
try:
    default_index = next((i for i, m in enumerate(rk_members) if getattr(m, "name", "").lower() in preferred), 0)
except Exception:
    default_index = 0
robot_kind = st.sidebar.selectbox(
    "Robot kind",
    options=rk_members,
    index=default_index,
    format_func=lambda m: getattr(m, "name", str(m)).capitalize(),
)

# Refresh behavior
refresh_sec = st.sidebar.number_input("Refresh interval (sec)", 1, 60, 5)
auto_refresh = st.sidebar.checkbox("Auto-refresh", True)

# Instantiate SDK once per run (cheap)
sdk = StandardBotsRobot(url=url, token=token, robot_kind=robot_kind)

# Method discovery trigger
with st.sidebar:
    if st.button("🔎 Discover methods (depth 2)", key="discover_btn"):
        with st.spinner("Scanning SDK object graph…"):
            with sdk.connection():
                methods = _discover_methods(sdk, max_depth=2)
        st.session_state["discovered_methods"] = methods

# =====================================================================================
# Main: endpoint selection + kwargs + invoke
# =====================================================================================

st.title("Standard Bots – Methods • Models • Responses")
st.caption("Call SDK endpoints and unwrap with `.ok()` to show real values.")

# Apply pending endpoint (from discovery panel) BEFORE creating the input widget
if "pending_endpoint" in st.session_state:
    st.session_state["endpoint_input"] = st.session_state.pop("pending_endpoint")

# Minimal presets — add more only after you verify names in your SDK
PRESETS = [
    "movement.brakes.get_brakes_state",
    "equipment.get_gripper_configuration",
]

st.markdown("#### Choose an SDK endpoint")
colA, colB = st.columns([2, 1])
endpoint_pick = colA.selectbox("Method path (dot notation)", PRESETS, index=0)
endpoint = colA.text_input(
    "…or type a method path",
    value=st.session_state.get("endpoint_input", endpoint_pick),
    key="endpoint_input",
    help="Example: movement.brakes.get_brakes_state",
)

kwargs_text = colB.text_area(
    "Method kwargs (JSONtry:
    call_kwargs = json.loads(kwargs_text) if kwargs_text.strip() else {}
except Exception as e:
    st.error(f"Invalid kwargs JSON: {e}")
    call_kwargs = {}

# Discovery results panel
if st.session_state.get("discovered_methods"):
    methods = st.session_state["discovered_methods"]
    with st.expander(f"Discovered methods ({len(methods)})", expanded=False):
        options = [m["path"] for m in methods]
        pick = st.selectbox("Pick a method", options, index=0, key="pick_discovered")
        sig = next((m["signature"] for m in methods if m["path"] == pick), "(...)")
        st.code(f"{pick}{sig}")
        use_col1, _ = st.columns([1, 3])
        if use_col1.button("Use selected", key="use_selected_btn"):
            # Defer applying to input until next run to avoid state-mutation errors
            st.session_state["pending_endpoint"] = pick
            _safe_rerun()

# Output slots (stable to reduce visible flicker)
result_slot = st.empty()
raw_slot = st.expander("Raw / Debug", expanded=False)

# Invoke once per run
with sdk.connection():
    try:
        method = _resolve_method(sdk, endpoint)
    except Exception as e:
        result_slot.error(str(e))
    else:
        # Show signature (best-effort)
        try:
            st.caption(f"Signature: `{endpoint}{inspect.signature(method)}`")
        except Exception:
            pass
        res = _call_ok_unwrap(method, **call_kwargs)
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
            _raw = _to_jsonable(res["raw"]) if res["raw"] is not None else None
            try:
                raw_slot.json(_raw)
            except Exception:
                raw_slot.write(_raw)

# Smoother auto-refresh: prefer st.autorefresh if available; otherwise fallback
if auto_refresh:
    if hasattr(st, "autorefresh"):
        st.autorefresh(interval=int(refresh_sec * 1000), key="autorefresh_key")
    else:
        time.sleep(refresh_sec)
        _safe_rerun()
