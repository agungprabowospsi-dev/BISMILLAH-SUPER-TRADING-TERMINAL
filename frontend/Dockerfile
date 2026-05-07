FROM node:18-alpine AS builder

WORKDIR /app

ARG CACHEBUST=5
RUN echo "Cache bust: $CACHEBUST"

COPY package*.json ./
RUN npm ci --silent

COPY . .
RUN npm run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html

RUN echo 'server { \
  listen 3000; \
  root /usr/share/nginx/html; \
  index index.html; \
  location / { \
    try_files $uri $uri/ /index.html; \
  } \
}' > /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]1
# rebuild Thu May  7 13:33:00 WIB 2026
