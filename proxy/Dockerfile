FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway.py .
# Default exit pool is empty (commented-out example entry) — an operator
# overrides this by bind-mounting their own exits.yml (see docs/PROXY.md).
COPY exits.example.yml exits.yml

EXPOSE 8888
CMD ["python", "gateway.py"]
