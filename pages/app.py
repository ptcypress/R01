# streamlit_sb_ok_demo.py — Simple/Advanced modes, method discovery, JSON-safe rendering
# Robust RobotKind selection and smoother auto-refresh. No JSON box in Simple mode.

import json
import time
import inspect
import dataclasses
from enum import Enum
from functools import reduce
import os

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
# Helpers (serialization, discovery, invocation)
# =====================================================================================

def _to_jsonable(obj):
    """Convert SDK returns (pydantic models, dataclasses, enums, bytes, etc.)
    into JSON-renderable Python primitives for st.json()."""
    try:
        if hasattr(obj, "model_dump") and callable(obj.model_dump):  # pydantic v2
            return obj.model_dump()
        if hasattr(obj, "dict") and callable(obj.dict):  # pydantic v1
            return obj.dict()
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, (bytes, bytearray)):
            return obj.decode(errors="replace")
        json.dumps(obj)  # probe serializability
        return obj
    except TypeError:
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
    """Invoke SDK method and unwrap via .ok(). If invocation fails, return debug info."""
    try:
        resp = method(**kwargs)
    except Exception as e:
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

refresh_sec = st.sidebar.number_input("Refresh interval (sec)", 1, 60, 5)
auto_refresh = st.sidebar.checkbox("Auto-refresh", True)

# Instantiate SDK once per run
sdk = StandardBotsRobot(url=url, token=token, robot_kind=robot_kind)

# Method discovery trigger
with st.sidebar:
    simple_mode = st.toggle("Simple mode", value=True, help="Hide advanced inputs; use presets + discovered methods.")
    if st.button("🔎 Discover methods (depth 2)", key="discover_btn"):
        with st.spinner("Scanning SDK object graph…"):
            with sdk.connection():
                methods = _discover_methods(sdk, max_depth=2)
        st.session_state["discovered_methods"] = methods

# Presets management (save/load/clear/reset)
DEFAULT_PRESETS = [
    "movement.brakes.get_brakes_state",
    "equipment.get_gripper_configuration",
]
if "presets" not in st.session_state:
    st.session_state["presets"] = DEFAULT_PRESETS.copy()

PRESETS_PATH = "/mnt/data/sb_presets.json"
with st.sidebar.expander("Manage presets", expanded=False):
    presets = st.session_state.get("presets", [])
    st.caption("Current presets:")
    st.code("
".join(presets) or "<empty>")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("Save", key="save_presets"):
            try:
                with open(PRESETS_PATH, "w") as f:
                    json.dump(presets, f, indent=2)
                st.success(f"Saved to {PRESETS_PATH}")
            except Exception as e:
                st.error(f"Save failed: {e}")
    with c2:
        if st.button("Load", key="load_presets"):
            if os.path.exists(PRESETS_PATH):
                try:
                    with open(PRESETS_PATH, "r") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        st.session_state["presets"] = data
                        _safe_rerun()
                    else:
                        st.error("File did not contain a list of strings.")
                except Exception as e:
                    st.error(f"Load failed: {e}")
            else:
                st.warning("No saved file found yet.")
    with c3:
        if st.button("Clear", key="clear_presets"):
            st.session_state["presets"] = []
            _safe_rerun()
    with c4:
        if st.button("Reset", key="reset_presets"):
            st.session_state["presets"] = DEFAULT_PRESETS.copy()
            _safe_rerun()

# =====================================================================================
# Main UI
# =====================================================================================

st.title("Standard Bots – Methods • Models • Responses")
st.caption("Call SDK endpoints and unwrap with `.ok()` to show real values.")

# Apply pending endpoint (from discovery panel) BEFORE creating widgets
if "pending_endpoint" in st.session_state:
    st.session_state["endpoint_input"] = st.session_state.pop("pending_endpoint")

# Minimal presets (dynamic). Modify via Manage presets sidebar or add from Discovered/Advanced.
presets = st.session_state.get("presets", [])

# -------------------- Simple Mode --------------------
if simple_mode:
    st.subheader("Pick a method")
    src = st.radio("Source", ["Presets", "Discovered"], horizontal=True)

    chosen = None
    if src == "Presets":
        if not presets:
            st.info("No presets yet. Add one from Discovered or Advanced.")
            chosen = None
        else:
            chosen = st.selectbox("Preset methods", presets, index=0, key="preset_pick")
            if st.button("➖ Remove from presets", key="remove_preset_btn") and chosen:
                try:
                    st.session_state["presets"].remove(chosen)
                except ValueError:
                    pass
                _safe_rerun()
    else:
        if not st.session_state.get("discovered_methods"):
            st.info("No discovered methods yet. Click 'Discover methods' in the sidebar.")
        else:
            disc = st.session_state["discovered_methods"]
            options = [m["path"] for m in disc]
            chosen = st.selectbox("Discovered methods", options, index=0, key="disc_pick")
            sig = next((m["signature"] for m in disc if m["path"] == chosen), "(...)")
            st.code(f"{chosen}{sig}")
            # Add to presets from discovered
            if chosen and st.button("➕ Add to presets", key="add_from_discovered_btn"):
                if chosen not in st.session_state["presets"]:
                    st.session_state["presets"].append(chosen)
                    _safe_rerun()
                else:
                    st.info("Already in presets.")

    # Build a tiny form for required kwargs (no JSON editing)
    call_kwargs = {}
    if chosen:
        try:
            method = _resolve_method(sdk, chosen)
            sig = inspect.signature(method)
            params = [p for p in sig.parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
            required = [p for p in params if p.default is p.empty]
            optional = [p for p in params if p.default is not p.empty]

            if required or optional:
                with st.expander("Parameters", expanded=bool(required)):
                    if required:
                        st.caption("Required")
                        for p in required:
                            v = st.text_input(f"{p.name}", key=f"arg:{chosen}:{p.name}")
                            if v != "":
                                try:
                                    call_kwargs[p.name] = json.loads(v)
                                except Exception:
                                    call_kwargs[p.name] = v  # fallback string
                    if optional:
                        show_opt = st.checkbox("Show optional parameters", value=False, key=f"opt:{chosen}")
                        if show_opt:
                            for p in optional:
                                default_repr = repr(p.default)
                                v = st.text_input(f"{p.name} (default {default_repr})", key=f"arg:{chosen}:{p.name}")
                                if v != "":
                                    try:
                                        call_kwargs[p.name] = json.loads(v)
                                    except Exception:
                                        call_kwargs[p.name] = v
        except Exception as e:
            st.error(str(e))
            chosen = None

    result_slot = st.empty()
    raw_slot = st.expander("Raw / Debug", expanded=False)

    if chosen and st.button("Call method", type="primary"):
        with sdk.connection():
            res = _call_ok_unwrap(_resolve_method(sdk, chosen), **call_kwargs)
        if res["success"]:
            result_slot.success(f"✅ {chosen} → 200 OK")
            _data = _to_jsonable(res["data"])
            try:
                st.json(_data)
            except Exception:
                st.write(_data)
        else:
            status = res.get("status")
            result_slot.error(f"❌ {chosen} failed (status={status}, stage={(res.get('raw') or {}).get('stage')})")
            _raw = _to_jsonable(res["raw"]) if res["raw"] is not None else None
            try:
                raw_slot.json(_raw)
            except Exception:
                raw_slot.write(_raw)

# -------------------- Advanced Mode --------------------
else:
    st.subheader("Advanced")
    st.markdown("Use dotted method path and raw JSON kwargs (original UI).")

    st.markdown("#### Choose an SDK endpoint")
    colA, colB = st.columns([2, 1])
    opt_list = presets if presets else [""]
    endpoint_pick = colA.selectbox("Method path (dot notation)", opt_list, index=0)
    endpoint = colA.text_input(
        "…or type a method path",
        value=st.session_state.get("endpoint_input", endpoint_pick),
        key="endpoint_input",
        help="Example: movement.brakes.get_brakes_state",
    )

    # Add/remove current endpoint to/from presets
    if endpoint.strip():
        b1, b2 = st.columns(2)
        with b1:
            if st.button("➕ Add to presets", key="add_from_adv"):
                if endpoint not in st.session_state["presets"]:
                    st.session_state["presets"].append(endpoint)
                    _safe_rerun()
                else:
                    st.info("Already in presets.")
        with b2:
            if st.button("➖ Remove from presets", key="remove_from_adv"):
                try:
                    st.session_state["presets"].remove(endpoint)
                    _safe_rerun()
                except ValueError:
                    st.info("Not in presets.")

    kwargs_text = colB.text_area(
        "Method kwargs (JSON)",
        value=st.session_state.get("kwargs_text", "{}"),
        height=120,
        help='e.g. {"axis":"x"} if the method takes parameters',
        key="kwargs_text",
    )

    try:
        call_kwargs = json.loads(kwargs_text) if kwargs_text.strip() else {}
    except Exception as e:
        st.error(f"Invalid kwargs JSON: {e}")
        call_kwargs = {}

    if st.session_state.get("discovered_methods"):
        methods = st.session_state["discovered_methods"]
        with st.expander(f"Discovered methods ({len(methods)})", expanded=False):
            options = [m["path"] for m in methods]
            pick = st.selectbox("Pick a method", options, index=0, key="pick_discovered")
            sig = next((m["signature"] for m in methods if m["path"] == pick), "(...)")
            st.code(f"{pick}{sig}")
            if st.button("Use selected", key="use_selected_btn"):
                st.session_state["pending_endpoint"] = pick
                _safe_rerun()

    result_slot = st.empty()
    raw_slot = st.expander("Raw / Debug", expanded=False)

    with sdk.connection():
        try:
            method = _resolve_method(sdk, endpoint)
        except Exception as e:
            result_slot.error(str(e))
        else:
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
