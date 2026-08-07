FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY doubao2api/ doubao2api/

ENV DOUBAO_HOST=0.0.0.0
ENV DOUBAO_PORT=9090

EXPOSE 9090

CMD ["python", "-m", "doubao2api"]
