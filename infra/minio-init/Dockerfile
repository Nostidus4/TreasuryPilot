FROM python:3.12.13-alpine

RUN pip install --no-cache-dir minio==7.2.18
COPY infra/minio-init/init.py /app/init.py

USER 65532:65532
ENTRYPOINT ["python", "/app/init.py"]
