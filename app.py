import streamlit as st
from PIL import Image
import io, os
import google.generativeai as genai

# Get your API key from Google Cloud Platform
api_key = os.environ.get("GOOGLE_API_KEY")
genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-1.5-flash")

# Define your prompt choices with descriptions
prompt_options = {
    "receipt_analysis": """
            This is the result of OCR on a grocery receipt.
            I need you to parse the receipt to only output a table of items and cost. 
            The first coloum should be name of grocery item and second should be costs. 
            Output in json format with keys "item", "cost" don't output anything except json.
            Some of the item names might have OCR errors, try to fix them to match items that might be close to existing products.
    """,
    "object_detection": "Identify objects within the image.",
    "scene_description": "Describe the overall scene and context.",
    "color_analysis": "Analyze the dominant colors and their distribution.",
    "text_extraction": "Extract any text visible within the image."
}

st.title("Gemini Image Analysis")

selected_prompt = st.selectbox("Select an analysis type:", list(prompt_options.keys()))

img_file_buffer = st.camera_input("Take a picture")

if img_file_buffer is not None:
    # To read image file buffer as a PIL Image:
    image = Image.open(img_file_buffer)

    if st.button("Analyze Image"):
        gemini_prompt = f"Analyze this image to perform the following {prompt_options[selected_prompt]}."

        try:
            response = model.generate_content(
                [
                    gemini_prompt,
                    image,
                ]
            )
            analysis = response.text
            st.write("## Analysis Results:")
            st.write(analysis)

        except Exception as e:
            st.error(f"Error processing image: {e}")