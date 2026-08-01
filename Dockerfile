# Railway deploy from monorepo root (GitHub: avinashwendor/ffmeg-vps)
# Builds reels-composer API — uses Debian ffmpeg for faster, reliable Railway builds.
# For source-compiled FFmpeg, see reels-composer/Dockerfile and set Root Directory to reels-composer.

FROM node:20-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY reels-composer/package.json ./
RUN npm install --omit=dev
COPY reels-composer/src ./src
COPY reels-composer/assets ./assets

ENV NODE_ENV=production
ENV PORT=3000

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["npm", "start"]
