FROM python:3.11-slim
WORKDIR /srv
# versions pinned to the ones the benchmark and stored runs were produced with
RUN pip install --no-cache-dir "pydantic-ai-slim[openai]==2.54.0" "openai==3.26.1" "fastapi==0.143.0" "uvicorn[standard]==0.54.0" "python-dotenv==1.2.4"
COPY . .
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
# single worker: run state (SSE subscribers) is in-process
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
