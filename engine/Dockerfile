# Движок «Правки» (Python): внутренний HTTP-сервис для веб-сервиса на Go. Наружу порт не публикуется.
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir lxml openpyxl pyyaml pymorphy3==2.0.6 pymorphy3-dicts-ru==2.4.417150.4580142 pypdf==6.21.2
COPY pravki ./pravki
# Учебные плейбуки — в образе; ваши плейбуки (playbooks/private) подключаются томом только для чтения.
COPY playbooks/*.yaml ./playbooks/
RUN useradd -r -U pravki && mkdir -p /app/playbooks/private && chown -R pravki /app
USER pravki
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request; r=urllib.request.Request('http://127.0.0.1:8000/health', headers={'X-Engine-Token': os.environ.get('ENGINE_TOKEN','')}); urllib.request.urlopen(r, timeout=4)"
CMD ["python", "-m", "pravki", "engine", "--host", "0.0.0.0", "--port", "8000"]
