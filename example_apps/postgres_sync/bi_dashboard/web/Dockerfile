# --- build ---
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json next.config.ts ./
COPY app/ ./app/
COPY components/ ./components/
COPY lib/ ./lib/

# NEXT_PUBLIC_* is inlined into the browser bundle at BUILD time, not read at
# runtime, so the data range has to be present here. Defaults keep the image
# buildable without them; pass --build-arg (or use docker-compose, which forwards
# them from .env.cube) to bake in your own data's bounds.
ARG NEXT_PUBLIC_DATA_START=2024-09-12
ARG NEXT_PUBLIC_DATA_END=2026-09-13
ARG NEXT_PUBLIC_DATA_END_TS=2026-09-13T00:00:00
ENV NEXT_PUBLIC_DATA_START=$NEXT_PUBLIC_DATA_START \
    NEXT_PUBLIC_DATA_END=$NEXT_PUBLIC_DATA_END \
    NEXT_PUBLIC_DATA_END_TS=$NEXT_PUBLIC_DATA_END_TS

RUN npm run build

# --- runtime ---
FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# `output: 'standalone'` emits a self-contained server plus only the node_modules
# it actually needs, so the runtime image does not carry the build toolchain.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
