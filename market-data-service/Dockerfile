FROM python:3.11-slim

WORKDIR /app

# Install runtime deps
COPY market-data-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy code (expects quantgambit-python available in build context)
COPY quantgambit-python /app/quantgambit-python
COPY market-data-service /app/market-data-service

ENV PYTHONPATH="/app/quantgambit-python:${PYTHONPATH}"

CMD ["python", "-m", "market-data-service.app"]
