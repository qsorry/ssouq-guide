FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY server.js ./
ENV PORT=80 DATA_DIR=/app/data NODE_ENV=production
EXPOSE 80
VOLUME ["/app/data"]
CMD ["node", "server.js"]
