FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --progress=off -r requirements.txt

COPY . .

EXPOSE 8050

CMD ["python", "-m", "fridge_dashboard.dash_app"]
