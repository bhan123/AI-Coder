FROM node:22-bookworm-slim AS frontend-build
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY --from=frontend-build /ui/dist ./web
RUN mkdir -p /app/data
EXPOSE 8010
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
