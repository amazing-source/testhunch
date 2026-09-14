# fastapi/fastapi (docs/adr/0011, 0013). `git` is what test_translate.py calls, and GitHub's runners have.
FROM ghcr.io/astral-sh/uv:0.12.13-python3.11-trixie-slim@sha256:d949a41f3b380660c009cbd023bb3645c6e203889de58faf22f3322e2bc2d436
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home runner \
    && mkdir /home/runner/.cache \
    && chown runner /home/runner/.cache
USER runner
WORKDIR /home/runner
# The image's Python, never one uv would download: a commit needing another cannot be built.
# No bytecode files: a mutant the same size as the original, written within the second, could
# otherwise run from the original's cached bytecode (docs/adr/0012).
ENV UV_PYTHON_DOWNLOADS=never UV_NO_PROGRESS=1 PYTHONDONTWRITEBYTECODE=1
