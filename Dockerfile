FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
COPY main.py main.py
RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=8080

CMD ["python", "main.py"]

