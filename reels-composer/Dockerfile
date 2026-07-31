# Stage 1 — official FFmpeg from git.ffmpeg.org
FROM debian:bookworm-slim AS ffmpeg-builder

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    pkg-config \
    yasm \
    nasm \
    libx264-dev \
    libmp3lame-dev \
    libass-dev \
    libfreetype6-dev \
    libvorbis-dev \
    zlib1g-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /build
# Official repo + stable release branch (matches ffmpeg.org release 8.1.x)
RUN git clone --depth 1 --branch release/8.1 https://git.ffmpeg.org/ffmpeg.git ffmpeg

WORKDIR /build/ffmpeg
RUN ./configure \
    --prefix=/usr/local \
    --enable-gpl \
    --enable-libx264 \
    --enable-libmp3lame \
    --enable-libass \
    --enable-libfreetype \
    --disable-debug \
    --disable-doc \
    --disable-ffplay \
  && make -j"$(nproc)" \
  && make install

# Stage 2 — Node render API + official FFmpeg binaries
FROM node:20-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    libx264-164 \
    libmp3lame0 \
    libass9 \
    libfreetype6 \
    libvorbis0a \
    libvorbisenc2 \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY --from=ffmpeg-builder /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg-builder /usr/local/bin/ffprobe /usr/local/bin/ffprobe
COPY --from=ffmpeg-builder /usr/local/lib/ /usr/local/lib/

ENV LD_LIBRARY_PATH=/usr/local/lib

WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev
COPY src ./src

ENV NODE_ENV=production
ENV PORT=3000

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["npm", "start"]
