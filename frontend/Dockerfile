FROM node:20-alpine AS build

WORKDIR /app
ARG VITE_PLOVER_API_TOKEN=""
ENV VITE_PLOVER_API_TOKEN=$VITE_PLOVER_API_TOKEN

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
