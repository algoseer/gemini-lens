# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
COPY . .

# Expose the port Flask will run on
EXPOSE 5000

# Start the Flask server
CMD ["flask", "run"]
