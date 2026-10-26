# Office Stock System - cloud backend image. Runs the Django app behind your host's HTTPS proxy.
# No secrets are baked in: every credential comes from the host's environment variables at run time.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DJANGO_DEBUG=false DJANGO_CACHE_BACKEND=database PORT=8000

RUN useradd --create-home --uid 10001 app
WORKDIR /srv/app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .

# Build the static files with throw-away values; real settings are supplied at run time.
RUN DJANGO_DEBUG=true python manage.py collectstatic --noinput && chown -R app:app /srv/app/staticfiles \
    && chmod +x docker/entrypoint.sh

USER app
EXPOSE 8000
# The probe must present an allowed Host header, or Django answers 400 (DisallowedHost).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
    CMD python -c "import os,urllib.request as u; h=os.environ.get('DJANGO_ALLOWED_HOSTS','localhost').split(',')[0].strip(); u.urlopen(u.Request('http://127.0.0.1:%s/health/' % os.environ.get('PORT','8000'), headers={'Host': h}), timeout=4)" || exit 1
ENTRYPOINT ["docker/entrypoint.sh"]
