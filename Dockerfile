FROM python:3.12-alpine
WORKDIR /app
# قراءة كود التحقّق آلياً (اختياري): tesseract + Pillow + pytesseract.
# غير حاسم للبناء: لو فشل التثبيت يظل الموقع يعمل ويُطلب الكود يدوياً (fallback بشري)،
# فلا ينكسر النشر بسبب الـ OCR.
RUN (apk add --no-cache tesseract-ocr && pip install --no-cache-dir pillow pytesseract) || \
    echo "OCR deps skipped — manual captcha fallback will be used"
# ملصقات قنوات Stremio (‏stremio_posters): Pillow يرسمها PNG، وfribidi لتشكيل الأسماء العربية واتجاهها (raqm في
# Pillow). غير حاسمٍ للبناء: بلاه تُرسم الملصقات SVG بالتصميم نفسه.
RUN (apk add --no-cache fribidi && pip install --no-cache-dir pillow) || \
    echo "Pillow/fribidi skipped — channel posters fall back to SVG"
# خدمة واتساب المسابقة: نسخة whatsapp-reader من النظام اللوجستي، يشغّلها الخادم داخل الحاوية على
# 127.0.0.1 فيُربط رقم المسابقة برقمٍ ثم رمز QR بلا إعداد. غير حاسمة للبناء: لو فشل التثبيت يظل الموقع
# يعمل وتقول صفحة المسابقة إن الخدمة غير مثبّتة. (git: مكتبة libsignal تُجلب من GitHub.)
COPY whatsapp-reader/package.json whatsapp-reader/package-lock.json ./whatsapp-reader/
# لا مفاتيح SSH داخل حاوية البناء: مكتبة libsignal مثبّتة في package-lock بعنوان git+ssh على GitHub،
# فيُعاد توجيه git إلى https ويُمنع أي انتظارٍ لإدخالٍ يدوي، كي تمرّ الخطوة بسرعة بدل أن تعلّق حتى المهلة ثم تُتجاوَز.
ENV GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="ssh -o BatchMode=yes -o StrictHostKeyChecking=no" NPM_CONFIG_UPDATE_NOTIFIER=false
RUN (apk add --no-cache nodejs npm git \
     && git config --global --add url."https://github.com/".insteadOf "ssh://git@github.com/" \
     && git config --global --add url."https://github.com/".insteadOf "git@github.com:" \
     && cd whatsapp-reader && npm ci --omit=dev --no-audit --no-fund \
     && (npm cache clean --force; apk del npm git; true)) || \
    (rm -rf whatsapp-reader/node_modules; echo "WhatsApp reader deps skipped — contest WhatsApp linking unavailable")
COPY whatsapp-reader/server.js ./whatsapp-reader/
COPY xm_lines.py xm_web.py falcon_api.py salla_api.py wa_send.py crypto_store.py guide_pages.py store_sitemap.py league.py tournament.py watch.py predict_page.py contest.py content.py content_page.py seo_db.py seo_match.py seo_build.py seo_search.py seo_sources.py seo_pages.py seo_qa.py seo_scan.py seo_release.py reports.py store_sync.py renew.py renew_import.py panels.py xlsx_write.py users_export.py user_links.py salla_web.py split_subs.py analytics.py google_api.py stremio_addon.py stremio_library.py stremio_posters.py stremio_categories.py stremio_accounts.py nuvio_accounts.py stremio_extras.py mail_inbox.py xm_lines.html admin.html setup.html login.html index.html renew.html renew_admin.html renew_report_tpl.html remaining.html contest_admin.html content_admin.html stats_admin.html report.html reports_admin.html stremio.html stremio_tool.html ./
COPY static ./static
COPY extension ./extension
RUN mkdir -p /app/data
ENV XM_BIND=0.0.0.0 XM_PORT=80 XM_MAIL_PORT=25 PYTHONUNBUFFERED=1
EXPOSE 80 25
VOLUME ["/app/data"]
CMD ["python", "xm_lines.py", "web"]
