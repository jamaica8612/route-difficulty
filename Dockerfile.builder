FROM python:3.11-slim
LABEL org.opencontainers.image.source="https://github.com/jamaica8612/route-difficulty"
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY scripts/requirements-data.txt ./scripts/requirements-data.txt
RUN pip install --no-cache-dir --requirement scripts/requirements-data.txt
COPY scripts ./scripts
ENTRYPOINT ["python", "scripts/build_dataset.py"]
CMD ["monthly"]
