# ClearGlass Agent Office console.
# Build from clearglass-agent-office/apps/web:  docker build -f ../../infra/docker/web.Dockerfile -t cg-office-web .
FROM node:22-slim AS build
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY . .
RUN npm run build

FROM node:22-slim
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /web/package.json /web/package-lock.json ./
RUN npm ci --omit=dev --no-fund --no-audit
COPY --from=build /web/.next ./.next
COPY --from=build /web/next.config.ts ./
USER node
EXPOSE 3000
CMD ["npx", "next", "start", "-p", "3000"]
