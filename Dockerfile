# The demo Django site with tokenguard installed from this repo.
# Built by docker-compose.yml; see docs/docker.md.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=demo_site.settings \
    PYTHONPATH=/app/demo \
    REDIS_URL=redis://redis:6379/0

WORKDIR /app

# Dependencies and the package first, so editing demo code does not reinstall them.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[dashboard]"

COPY demo ./demo
COPY docker/entrypoint.sh /entrypoint.sh

# Not root: the process only needs to write the demo's SQLite file.
RUN useradd --create-home app && chmod +x /entrypoint.sh && chown -R app /app
USER app

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "demo_site.asgi:application"]
