FROM python:3.12-slim
WORKDIR /app
COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/api/app ./app
COPY services/api/evals ./evals
COPY knowledge /knowledge
ENV PYTHONPATH=/app POLICY_PATH=/knowledge/PROCUREMENT_POLICY.md
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:' + os.getenv('PORT', '8000') + '/health')"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
