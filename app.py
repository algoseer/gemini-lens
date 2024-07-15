from flask import Flask, render_template, request
from PIL import Image
import io, os
import requests
import google.generativeai as genai
#from google.api_core.client_options import ClientOptions


app = Flask(__name__)

# Get your API key from Google Cloud Platform
api_key = os.environ.get("GOOGLE_API_KEY")

#client_options = ClientOptions(api_endpoint='us-west-aiplatform.googleapis.com')
genai.configure(api_key = api_key)
model = genai.GenerativeModel("gemini-pro-vision")

# Define your prompt choices with descriptions
prompt_options = {
    "object_detection": "Identify objects within the image.",
    "scene_description": "Describe the overall scene and context.",
    "color_analysis": "Analyze the dominant colors and their distribution.",
    "text_extraction": "Extract any text visible within the image."
}

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Get the image file and selected prompt
        image_file = request.files["image"]
        selected_prompt = request.form.get("prompt")

        # Generate the prompt for Gemini
        gemini_prompt = f"Analyze this image to perform the following {selected_prompt}."

        # Prepare the image for Gemini
        image_bytes = image_file.read()
        image_pil = Image.open(io.BytesIO(image_bytes))

        # Call Gemini for analysis
        try:
            response = model.generate_content(
                [
                    gemini_prompt,
                    image_pil,
                ]
            )
            analysis = response.text

        except Exception as e:
            analysis = f"Error processing image: {e}" 

        return render_template("results.html", analysis=analysis, prompt=selected_prompt)

    return render_template("index.html", prompts=prompt_options)

if __name__ == "__main__":
    app.run(debug=True)
