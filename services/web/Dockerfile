FROM python:3.11-slim
WORKDIR /app
COPY services/web/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/web/app ./app
COPY services/web/static ./static
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
