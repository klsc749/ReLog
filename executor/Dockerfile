ARG D4J_BASE_IMAGE=d4j-base:latest
FROM ${D4J_BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    zstd \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY d4j_executor /app/d4j_executor
COPY pyproject.toml /app/pyproject.toml

RUN python3 -m venv /app/.venv \
  && /app/.venv/bin/python -m pip install --no-cache-dir -U pip \
  && /app/.venv/bin/python -m pip install --no-cache-dir tree-sitter==0.25.2 tree-sitter-java==0.23.5

RUN mkdir -p /opt/agent
COPY agent/SystemOutHookAgent.jar /opt/agent/SystemOutHookAgent.jar

ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH=/app

ENTRYPOINT ["/app/.venv/bin/python", "-m", "d4j_executor.run"]
