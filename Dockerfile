FROM python:3.12-alpine
WORKDIR /app
COPY xm_lines.py xm_lines.html ./
ENV XM_BIND=0.0.0.0 XM_PORT=80 PYTHONUNBUFFERED=1
EXPOSE 80
CMD ["python", "xm_lines.py", "web"]
