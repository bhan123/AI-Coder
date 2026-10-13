FROM node:22-bookworm-slim AS frontend-build
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm test && npm run build

# Keep the already-running Python environment for this code-only release.
FROM signal-forge:rollback-20260909-v060 AS runtime
WORKDIR /app
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY --from=frontend-build /ui/dist ./web
