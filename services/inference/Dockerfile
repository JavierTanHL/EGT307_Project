FROM python:3.11-slim
ENV TF_CPP_MIN_LOG_LEVEL=2 PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/inference/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/inference/app ./app
COPY models ./models
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
