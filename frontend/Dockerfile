FROM nginx:1.27-alpine
COPY dist /usr/share/nginx/html
RUN printf 'server {\n  listen 3000;\n  root /usr/share/nginx/html;\n  index index.html;\n  location ~* \\.html$ {\n    add_header Cache-Control "no-cache, must-revalidate";\n    add_header Pragma "no-cache";\n    try_files $uri $uri/ /index.html;\n  }\n  location ~* \\.(js|css)$ {\n    add_header Cache-Control "public, max-age=31536000, immutable";\n  }\n  location / {\n    try_files $uri $uri/ /index.html;\n  }\n}\n' > /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
