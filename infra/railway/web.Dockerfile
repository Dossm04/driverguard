FROM node:22-alpine
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci
# Public addresses are compiled into Next.js, so set them BEFORE this build.
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ARG INTERNAL_API_ORIGIN
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL \
    INTERNAL_API_ORIGIN=$INTERNAL_API_ORIGIN \
    NEXT_PUBLIC_DEMO_HINTS=0 \
    NEXT_TELEMETRY_DISABLED=1
RUN test -n "$NEXT_PUBLIC_API_URL" && test -n "$NEXT_PUBLIC_WS_URL" \
    && test -n "$INTERNAL_API_ORIGIN"
COPY web/ ./
RUN mkdir -p public/models && for m in face_landmarker hand_landmarker; do \
      wget -q -T 60 -t 3 -O public/models/$m.task \
      https://storage.googleapis.com/mediapipe-models/$m/$m/float16/1/$m.task \
      || exit 1; \
    done
RUN npm run build
ENV NODE_ENV=production PORT=3000
EXPOSE 3000
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0"]
