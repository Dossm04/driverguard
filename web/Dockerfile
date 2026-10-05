# Веб-панель DriverGuard (Next.js 15)
FROM node:22-alpine

WORKDIR /app

# Сначала зависимости — для кэширования слоёв
COPY package.json package-lock.json ./
RUN npm ci

# NEXT_PUBLIC_* вшиваются в клиентский бандл при сборке — передаются build-args из compose
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/live
ARG NEXT_PUBLIC_MAP_TILES_LIGHT=
ARG NEXT_PUBLIC_MAP_TILES_DARK=
ARG NEXT_PUBLIC_MP_WASM_URL=
ARG NEXT_PUBLIC_DEMO_HINTS=
ENV INTERNAL_API_ORIGIN=http://backend:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL \
    NEXT_PUBLIC_MAP_TILES_LIGHT=$NEXT_PUBLIC_MAP_TILES_LIGHT \
    NEXT_PUBLIC_MAP_TILES_DARK=$NEXT_PUBLIC_MAP_TILES_DARK \
    NEXT_PUBLIC_MP_WASM_URL=$NEXT_PUBLIC_MP_WASM_URL \
    NEXT_PUBLIC_DEMO_HINTS=$NEXT_PUBLIC_DEMO_HINTS

# Исходники и сборка
COPY . .
# Модель MediaPipe (3,7 МБ) — копия на своём сервере: камера работает без Google Storage
# и после подготовки PWA без интернета. Не выпускаем неполную сборку.
RUN mkdir -p public/models && for m in face_landmarker hand_landmarker; do \
      if [ -s public/models/$m.task ]; then continue; fi; \
      wget -q -T 60 -t 3 -O public/models/$m.task \
        https://storage.googleapis.com/mediapipe-models/$m/$m/float16/1/$m.task \
      || { echo "Required offline model $m could not be downloaded"; exit 1; }; \
    done
RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
