import time, requests, pandas as pd, streamlit as st

ROBOT = "http://10.17.2.107:3000"
TOKEN = st.secrets.get("ro1_token", "l3a5ymfq-mq7vijtf-61phhms3-sbqpe")
VAR_ID = st.text_input("Variable ID", "speed_rpm")  # or a GUID if required by your API

headers = {"Authorization": f"Bearer {TOKEN}"}
st.title("RO1 Live via REST")
chart_ph = st.empty()
vals = []

while True:
    try:
        r = requests.get(f"{ROBOT}/api/v1/routine-editor/variables/{VAR_ID}",
                         headers=headers, timeout=3)
        r.raise_for_status()
        value = r.json().get("value")   # adjust to the field name in the response
        vals.append({"t": pd.Timestamp.utcnow(), "value": value})
        df = pd.DataFrame(vals).set_index("t").tail(300)
        chart_ph.line_chart(df["value"])
    except Exception as e:
        st.warning(f"REST error: {e}")
    time.sleep(1)
