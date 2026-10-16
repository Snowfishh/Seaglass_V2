# Hosted demo image, deployed as a Render Docker web service. See deploy/render/README.md.
# Runs the offline provider over the fictional fixture only; keys and the database are
# generated fresh at every container start and nothing survives a restart.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt/build
COPY requirements.lock pyproject.toml ./
RUN pip install -r requirements.lock
COPY src ./src
RUN pip install --no-deps --no-build-isolation . && rm -rf /opt/build

RUN useradd --create-home --uid 1000 user
USER user
ENV HOME=/home/user
WORKDIR /home/user/app
COPY --chown=user data ./data

# Hosted mode is fixed on in this image. ASPIRE_ALLOWED_HOSTS has no default: set it as a
# service environment variable, or the service refuses to start.
ENV ASPIRE_HOSTED_DEMO=true \
    ASPIRE_DEMO_MODE=true \
    ASPIRE_PROVIDER_MODE=offline_extractive \
    ASPIRE_PLATFORM_SOURCE=fixture

EXPOSE 7860
CMD ["sh", "-c", "rm -rf var .env && python -m aspire_brain.cli init-demo && exec python -m uvicorn aspire_brain.main:app --host 0.0.0.0 --port 7860 --no-proxy-headers --no-access-log"]
