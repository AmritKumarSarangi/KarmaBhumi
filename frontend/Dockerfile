# ============================================================
# Stage 1: Build static files
# ============================================================
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package.json ./
RUN npm install

# Copy source code and build
COPY tsconfig.json tsconfig.node.json vite.config.ts index.html ./
COPY src/ ./src

RUN npm run build

# ============================================================
# Stage 2: Serve using Nginx
# ============================================================
FROM nginx:alpine

# Copy nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy build output from Stage 1
COPY --from=builder /app/dist /usr/share/nginx/html

# Expose HTTP port
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
