FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/workspace

WORKDIR /workspace

COPY app/backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend-requirements.txt

COPY app/__init__.py /workspace/app/__init__.py
COPY app/backend /workspace/app/backend
COPY ["app/Story Analyzer", "/workspace/app/Story Analyzer"]
RUN mkdir -p /workspace/app/data/local_project

EXPOSE 8000
CMD ["uvicorn", "app.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
