FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY index.js ./
RUN mkdir -p /app/auth
ENV WA_PORT=80 WA_BIND=0.0.0.0 WA_AUTH_DIR=/app/auth NODE_ENV=production
EXPOSE 80
CMD ["node", "index.js"]
