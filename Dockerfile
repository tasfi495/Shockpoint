# One container: FastAPI engine + API + static frontend. Built for Hugging Face Spaces (Docker SDK).
# Spaces run the container as user 1000 and send traffic to port 7860 (app_port in README.md).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=7860

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH
WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=user . .
# Rebuild the synthetic data (fixed seed) so order due dates sit in the next 60 days from build day.
RUN python scripts/generate_data.py

EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
