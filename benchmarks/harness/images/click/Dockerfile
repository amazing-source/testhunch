# pallets/click (docs/adr/0011). `less` is what click's pager tests call, and GitHub's runners have.
FROM ghcr.io/astral-sh/uv:0.12.13-python3.12-trixie-slim@sha256:87bc72093c0aa93cc962bd7c0498ddf416dad3ce9e1434724e936e02b72afe5d
RUN apt-get update \
    && apt-get install -y --no-install-recommends less \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home runner \
    && mkdir /home/runner/.cache \
    && chown runner /home/runner/.cache
USER runner
WORKDIR /home/runner
# The image's Python, never one uv would download: a commit needing another cannot be built.
ENV UV_PYTHON_DOWNLOADS=never UV_NO_PROGRESS=1
