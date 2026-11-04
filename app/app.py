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
    st.Page("views/data_quality.py", title="Data Quality", icon="🧪"),
]

pg = st.navigation(pages)

with st.sidebar:
    st.caption(
        "Synthetic data, not real patient data.\n\n"
        "The table layout follows published hospital-database designs. Every number and "
        "proportion (diagnosis mix, age, stay length, occupancy, charges) is chosen, not "
        "measured from real hospitals, so findings describe this dataset, not the real world. "
        "[Sources and details](https://github.com/brianravelo28/synthetic-hospital-db/blob/main/docs/CITATIONS.md)"
    )

pg.run()
