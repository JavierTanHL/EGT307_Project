FROM python:3.11-slim
WORKDIR /app
COPY services/storage/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/storage/app ./app
RUN mkdir -p /data/images
EXPOSE 8002
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
