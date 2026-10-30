FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY copilot copilot
COPY scripts scripts
COPY admin_ui admin_ui
COPY Makefile .
# data/ (выдача кейса), models/ (make train) и var/ (база обращений SQLite) монтируются при запуске:
# docker run -v $PWD/data:/app/data -v $PWD/models:/app/models -v $PWD/var:/app/var -p 8000:8000 copilot
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "copilot.api:app", "--host", "0.0.0.0", "--port", "8000"]
