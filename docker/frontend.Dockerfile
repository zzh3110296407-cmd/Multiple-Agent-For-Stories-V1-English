FROM node:22-alpine AS build

WORKDIR /workspace/app/frontend

COPY app/frontend/package*.json ./
RUN npm ci

COPY app/frontend ./
ARG VITE_API_BASE_URL=/
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/app/frontend/dist /usr/share/nginx/html
EXPOSE 80
