# Fantasy GM API. Defaults to the public demo: no ESPN cookies or API keys needed, and the
# made-up league is rebuilt on every start, so the container needs no persistent disk.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home app && mkdir /data && chown app /data
USER app

ENV FGM_DEMO_MODE=true \
    FGM_DATABASE_URL=sqlite:////data/fantasy_gm.db \
    PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec fgm serve --host 0.0.0.0 --port ${PORT}"]
