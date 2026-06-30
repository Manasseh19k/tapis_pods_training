FROM python:3.12-slim

# Install Node.js
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm supervisor && \
    rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Python — copy only the files uv and the app need
COPY tapis-pods-training-20260610/pyproject.toml tapis-pods-training-20260610/uv.lock ./backend/
RUN uv sync --locked --no-install-project --project /app/backend
COPY tapis-pods-training-20260610/agent_testing_assignment_rust_rag.py ./backend/
COPY ["tapis-pods-training-20260610/Rust Atomics and Locks.txt", "./backend/"]

# Node — install dependencies first, then copy source
COPY my-copilot-app/package.json my-copilot-app/package-lock.json ./frontend/
RUN cd frontend && npm ci --legacy-peer-deps
COPY my-copilot-app/app ./frontend/app/
COPY my-copilot-app/public ./frontend/public/
COPY my-copilot-app/next.config.js ./frontend/
COPY my-copilot-app/tsconfig.json ./frontend/
COPY my-copilot-app/postcss.config.mjs ./frontend/
COPY my-copilot-app/eslint.config.mjs ./frontend/
COPY my-copilot-app/next-env.d.ts ./frontend/
RUN cd frontend && npm run build && \
    cp -r .next/static .next/standalone/.next/static && \
    cp -r public .next/standalone/public

RUN cp -r /app/frontend/.next/static /app/frontend/.next/standalone/.next/static && \
    cp -r /app/frontend/public /app/frontend/.next/standalone/public


COPY supervisord.conf /etc/supervisor/supervisord.conf

EXPOSE 3000 8000
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/supervisord.conf"]