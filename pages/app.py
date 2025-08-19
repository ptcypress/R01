import time
import streamlit as st
from pymodbus.client import ModbusTcpClient

st.set_page_config(page_title="RO1 Live Modbus", layout="wide")

IP = st.text_input("Server IP", "10.2.17.107")
PORT = st.number_input("Port", 1, 65535, 502)
ADDR = st.number_input("Holding register offset (e.g., HR1=0)", 0, 9999, 0)
NREG = st.number_input("Count", 1, 10, 1)

@st.cache_resource
def get_client(ip, port):
    c = ModbusTcpClient(ip, port=port, timeout=2)
    c.connect()
    return c

client = get_client(IP, PORT)
placeholder = st.empty()
run = st.checkbox("Live refresh (1 Hz)", value=True)

hist = []

while run:
    rr = client.read_holding_registers(ADDR, NREG)
    if rr.isError():
        placeholder.error(f"Read error: {rr}")
    else:
        vals = rr.registers
        hist.append(vals[0])
        col1, col2 = st.columns(2)
        with col1:
            st.metric("HR value", vals[0])
        with col2:
            st.line_chart(hist)
    time.sleep(1)
    run = st.session_state.get("Live refresh (1 Hz)", True)
