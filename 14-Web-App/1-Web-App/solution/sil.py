import streamlit as st
import pickle

model = pickle.load(open('ufo-model.pkl','rb'))

st.title("Prediction of UFO Sightings")

st.markdown("Enter the duration (seconds), for latitude 40, and longitude -12 of the UFO sighting to predict the country of the UFO sighting")

dur = st.text_input('', 0,10000)

# Prediction
st.subheader("Prediction")
st.code(int(model.predict([[int(dur), 40, -12]])))