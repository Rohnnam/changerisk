# The hosted dashboard as a container: `changerisk serve --hosted`, no repository needed.
#
#   docker build -t changerisk .
#   docker run --rm -p 7860:7860 -e GITHUB_TOKEN=... changerisk
#
# See docs/DEPLOY.md for the settings and for running it behind a reverse proxy.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
COPY frontend ./frontend
RUN pip install . && rm -rf /build

# Hugging Face and most platforms run containers as uid 1000; do the same everywhere.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app
USER app
WORKDIR /home/app

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7860/api/health', timeout=4).status == 200 else 1)"

CMD ["changerisk", "serve", "--hosted", "--host", "0.0.0.0", "--port", "7860"]
