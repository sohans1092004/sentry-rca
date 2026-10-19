# One image for every Python component; compose picks the command.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.16 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/venv PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY common common
COPY processors processors
COPY alerting alerting
COPY services services
COPY injector injector
COPY recorder recorder
COPY investigation investigation
COPY evals evals
COPY runbooks runbooks
RUN uv sync --frozen --no-dev
