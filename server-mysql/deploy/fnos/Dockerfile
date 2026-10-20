ARG NODE_IMAGE=node:22.16.0-alpine3.22
FROM ${NODE_IMAGE} AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12.11-alpine3.22 AS configuration
WORKDIR /source
COPY tools/prepare_config_yaml.py tools/prepare_config_yaml.py
COPY datatable_json/ datatable_json/
COPY server-mysql/testdata/SkillLogicConfig server-mysql/testdata/SkillLogicConfig
RUN python tools/prepare_config_yaml.py --output /bootstrap
COPY server-mysql/config/operations/ /operations/
RUN cp /operations/*.yaml /bootstrap/tables/ && rm /bootstrap/tables/CustomSkins.yaml

FROM golang:1.25.0-alpine3.22 AS build
WORKDIR /source
COPY server-mysql/go.mod server-mysql/go.sum ./
ARG GOPROXY=https://goproxy.cn,direct
ENV GOPROXY=${GOPROXY}
RUN go mod download
COPY server-mysql/ ./
ENV CGO_ENABLED=0 GOOS=linux GOARCH=amd64
# time.Local initialization in scratch cannot use ZONEINFO alone: embed the
# database so TZ=Asia/Shanghai also governs daily resets and activity dates.
RUN go build -tags timetzdata -trimpath -buildvcs=false -ldflags="-s -w" -o /out/mhqserver . && \
    go build -tags timetzdata -trimpath -buildvcs=false -ldflags="-s -w" -o /out/gm-api ./cmd/gm-api && \
    go build -tags timetzdata -trimpath -buildvcs=false -ldflags="-s -w" -o /out/gm-admin ./cmd/gm-admin && \
    go build -tags timetzdata -trimpath -buildvcs=false -ldflags="-s -w" -o /out/import-config ./cmd/import-config && \
    go build -tags timetzdata -trimpath -buildvcs=false -ldflags="-s -w" -o /out/publish-config ./cmd/publish-config && \
    go build -tags timetzdata -trimpath -buildvcs=false -ldflags="-s -w" -o /out/healthcheck ./cmd/healthcheck
COPY --from=configuration /bootstrap /bootstrap
RUN /out/import-config -validate-only -table /bootstrap/tables -skill-logic /bootstrap/SkillLogicConfig.yaml

FROM alpine:3.22 AS tools
COPY --from=build /out/ /usr/local/bin/
COPY --from=configuration /bootstrap/ /bootstrap/
COPY --from=build /usr/local/go/lib/time/zoneinfo.zip /zoneinfo.zip
ENV ZONEINFO=/zoneinfo.zip
USER 65532:65532
WORKDIR /app

FROM alpine:3.22 AS game
COPY --from=build /out/mhqserver /out/healthcheck /
COPY --from=build /out/import-config /usr/local/bin/import-config
COPY --from=configuration /bootstrap/ /bootstrap/
COPY server-mysql/deploy/fnos/entrypoints/game.sh /entrypoint.sh
COPY --from=build /usr/local/go/lib/time/zoneinfo.zip /zoneinfo.zip
ENV ZONEINFO=/zoneinfo.zip
USER 65532:65532
WORKDIR /app
EXPOSE 7756
ENTRYPOINT ["sh", "/entrypoint.sh"]

FROM alpine:3.22 AS gm-api
COPY --from=build /out/gm-api /out/healthcheck /
COPY --from=build /out/gm-admin /usr/local/bin/gm-admin
COPY --from=web /web/dist/ /web/
COPY server-mysql/deploy/fnos/entrypoints/gm-api.sh /entrypoint.sh
COPY --from=build /usr/local/go/lib/time/zoneinfo.zip /zoneinfo.zip
ENV ZONEINFO=/zoneinfo.zip GM_WEB_ROOT=/web
USER 65532:65532
WORKDIR /app
EXPOSE 8080
ENTRYPOINT ["sh", "/entrypoint.sh"]
