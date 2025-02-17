# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir --progress-bar off -r requirements.txt

# Expose the port Flask will run on
EXPOSE 8501

# Start the Flask server
CMD ["streamlit", "run","app.py","--server.address","0.0.0.0"]
