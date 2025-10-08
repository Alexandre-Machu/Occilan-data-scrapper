import streamlit as st

st.set_page_config(page_title="Smoke test")
st.title("Smoke test")
st.write("If you see this, Streamlit stays running.")
if st.button('No-op button'):
    st.write('clicked')
