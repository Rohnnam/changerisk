# Hugging Face Space image. It installs ChangeRisk straight from the GitHub repository at a pinned
# ref, so this Space repository only needs this file and the README. To release a new version,
# change CHANGERISK_REF (a tag or a commit) and push; Hugging Face rebuilds.

FROM python:3.12-slim

ARG CHANGERISK_REF=main

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install "https://github.com/Rohnnam/changerisk/archive/${CHANGERISK_REF}.zip"

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app
USER app
WORKDIR /home/app

# Behind Hugging Face's proxy the visitor's address is the last X-Forwarded-For entry. The Space
# page frames the app, so that origin is allowed to. A GITHUB_TOKEN secret (read-only, no scopes)
# raises GitHub's rate limit from 60 to 5,000 requests an hour; set it in the Space settings.
ENV CHANGERISK_TRUSTED_PROXIES=1 \
    CHANGERISK_FRAME_ANCESTORS="https://huggingface.co,https://*.huggingface.co"

EXPOSE 7860
CMD ["changerisk", "serve", "--hosted", "--host", "0.0.0.0", "--port", "7860"]
