import streamlit as st

st.set_page_config(
    page_title="Hospital Operations Dashboard",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

pages = [
    st.Page("views/overview.py", title="Overview", icon="🏥", default=True),
    st.Page("views/admissions.py", title="Admissions & Census", icon="🛏️"),
    st.Page("views/clinical.py", title="Clinical", icon="🩺"),
    st.Page("views/staffing.py", title="Staffing", icon="👩‍⚕️"),
    st.Page("views/financials.py", title="Financials", icon="💰"),
]

pg = st.navigation(pages)

with st.sidebar:
    st.caption(
        "Synthetic data — generated + constraint-repaired via "
        "hospital_generator.py / validate_repair.py. Not real patient data."
    )

pg.run()
