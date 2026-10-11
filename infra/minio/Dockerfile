FROM golang:1.24.2-alpine3.21 AS build

ARG MINIO_VERSION=RELEASE.2025-04-22T22-12-26Z

RUN apk add --no-cache git
RUN git clone --depth 1 --branch "${MINIO_VERSION}" https://github.com/minio/minio.git /src

WORKDIR /src
ENV CGO_ENABLED=0
RUN go build -trimpath -ldflags="-s -w" -o /out/minio .

FROM alpine:3.21

RUN apk add --no-cache ca-certificates curl \
    && addgroup -S minio \
    && adduser -S -G minio -h /data minio \
    && mkdir -p /data \
    && chown minio:minio /data

COPY --from=build /out/minio /usr/local/bin/minio

USER minio
VOLUME ["/data"]
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
