FROM python:3.12-alpine
WORKDIR /app
COPY xm_lines.py guide_pages.py store_sitemap.py whatsapp.py xm_lines.html admin.html setup.html login.html index.html whatsapp.html wa_gate.html ./
COPY static ./static
RUN mkdir -p /app/data
ENV XM_BIND=0.0.0.0 XM_PORT=80 PYTHONUNBUFFERED=1
EXPOSE 80
VOLUME ["/app/data"]
CMD ["python", "xm_lines.py", "web"]
