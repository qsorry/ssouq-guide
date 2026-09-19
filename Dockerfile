FROM python:3.12-alpine
WORKDIR /app
# قراءة كود التحقّق آلياً (اختياري): tesseract + Pillow + pytesseract.
# غير حاسم للبناء: لو فشل التثبيت يظل الموقع يعمل ويُطلب الكود يدوياً (fallback بشري)،
# فلا ينكسر النشر بسبب الـ OCR.
RUN (apk add --no-cache tesseract-ocr && pip install --no-cache-dir pillow pytesseract) || \
    echo "OCR deps skipped — manual captcha fallback will be used"
COPY xm_lines.py xm_web.py falcon_api.py crypto_store.py guide_pages.py store_sitemap.py xm_lines.html admin.html setup.html login.html index.html ./
COPY static ./static
RUN mkdir -p /app/data
ENV XM_BIND=0.0.0.0 XM_PORT=80 PYTHONUNBUFFERED=1
EXPOSE 80
VOLUME ["/app/data"]
CMD ["python", "xm_lines.py", "web"]
