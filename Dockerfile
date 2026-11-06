FROM node:24.18.0-bookworm-slim AS frontend
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./

FROM frontend AS frontend-checks
RUN npm run check && npm test

FROM frontend AS frontend-build
RUN npm run build

FROM python:3.14.6-slim AS backend
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY backend/requirements.txt ./
RUN python -m pip install --no-cache-dir --no-deps -r requirements.txt
COPY backend/vestor_api.py ./
COPY backend/vestor_domain/ ./vestor_domain/

FROM backend AS backend-checks
COPY backend/requirements-checks.txt ./
RUN python -m pip install --no-cache-dir --no-deps -r requirements-checks.txt
COPY backend/tests/ ./tests/
RUN python -m pip check \
    && python -S -c "from vestor_domain.decimal_example import add_decimals" \
    && python -m pytest \
    && python -m mypy --strict vestor_api.py vestor_domain

FROM backend AS runtime
COPY --from=frontend-build /app/dist/ ./static/
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "vestor_api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
