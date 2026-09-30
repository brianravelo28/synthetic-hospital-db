import streamlit as st

from utils import BASE_CSS

st.set_page_config(
    page_title="Hospital Operations Dashboard",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(BASE_CSS, unsafe_allow_html=True)

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
        "hospital_generator.py / validate_repair.py.\n\n"
        "Not real patient data."
    )

pg.run()
