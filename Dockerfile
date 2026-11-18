FROM python:3.12-alpine

WORKDIR /app
COPY app/ /app/app/
RUN mkdir -p /data

ENV DATA_DIR=/data PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
VOLUME ["/data"]

CMD ["python", "-m", "app.main"]
