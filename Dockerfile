FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html logo.jpg og-image.png robots.txt sitemap.xml /usr/share/nginx/html/
EXPOSE 80
