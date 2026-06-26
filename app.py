import streamlit as st

st.set_page_config(page_title="TSP Rebalance App", layout="wide")
st.title("TSP Rebalance App")

st.write("This is a starter version.")
st.write("Next we will add live data and allocation logic.")

st.sidebar.header("Inputs")
g = st.sidebar.number_input("G %", value=40.0)
c = st.sidebar.number_input("C %", value=30.0)
i = st.sidebar.number_input("I %", value=20.0)
s = st.sidebar.number_input("S %", value=5.0)
f = st.sidebar.number_input("F %", value=5.0)

total = g + c + i + s + f

st.subheader("Current Allocation")
st.write({"G": g, "C": c, "I": i, "S": s, "F": f})
st.write(f"Total: {total:.1f}%")

if total != 100:
    st.warning("Allocation does not sum to 100%.")
else:
    st.success("Allocation sums to 100%.")
