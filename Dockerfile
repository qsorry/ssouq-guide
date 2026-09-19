FROM python:3.12-alpine
WORKDIR /app
# قراءة كود التحقّق آلياً (اختياري): tesseract + Pillow + pytesseract.
# لو حُذفت هذه السطور يظل الموقع يعمل — يُطلب الكود يدوياً عند الإنشاء (fallback بشري).
RUN apk add --no-cache tesseract-ocr \
    && pip install --no-cache-dir pillow pytesseract
COPY xm_lines.py xm_web.py guide_pages.py store_sitemap.py xm_lines.html admin.html setup.html login.html index.html ./
COPY static ./static
RUN mkdir -p /app/data
ENV XM_BIND=0.0.0.0 XM_PORT=80 PYTHONUNBUFFERED=1
EXPOSE 80
VOLUME ["/app/data"]
CMD ["python", "xm_lines.py", "web"]
