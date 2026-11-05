# Agent 层：固定版本的 omp 加一个 stdio↔unix socket 转发器。omp 只从 stdin/stdout 说 ACP，转发器让桥能跨容器连进来。
FROM public.ecr.aws/docker/library/debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2

ARG TARGETARCH
ARG OMP_VERSION=18.16.0
ARG OMP_X64_SHA256=6498ed785bab00d2926e0387e0ec02362d6d45f1c3d0d1b57c1618b7f95c9264
ARG OMP_ARM64_SHA256=c2be1ea85ce17c4270854b57efff2a7ea1d5a03c7557fd08721f2b9bb32698de

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 \
    && rm -rf /var/lib/apt/lists/*
# 上游只在 GitHub Releases 发二进制，没有官方镜像；按版本和 SHA-256 固定，不装 npm 包也不自己编。
RUN case "$TARGETARCH" in \
      amd64) asset=omp-linux-x64; checksum="$OMP_X64_SHA256" ;; \
      arm64) asset=omp-linux-arm64; checksum="$OMP_ARM64_SHA256" ;; \
      *) echo "不支持的架构 $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && curl --fail --silent --show-error --location \
         "https://github.com/can1357/oh-my-pi/releases/download/v${OMP_VERSION}/${asset}" \
         --output /usr/local/bin/omp \
    && echo "$checksum  /usr/local/bin/omp" | sha256sum --check --strict \
    && chmod 0755 /usr/local/bin/omp \
    && mkdir -p /data/agent/home /workspace /data/run /usr/share/doc/wonton-omp \
    && groupadd --system --gid 65532 wonton \
    && useradd --system --uid 65532 --gid 65532 --no-create-home wonton

COPY agent-entrypoint.py /usr/local/bin/wonton-omp-agent
COPY LICENSE.omp /usr/share/doc/wonton-omp/LICENSE
# 帮助 skill 放镜像里：HOME 是挂载点，configs 不能挂进挂载点里，入口脚本启动时把它放到 HOME。
COPY wonton-help /usr/local/share/wonton-omp/skills/wonton-help
RUN chmod 0755 /usr/local/bin/wonton-omp-agent \
    && chmod 0644 /usr/share/doc/wonton-omp/LICENSE /usr/local/share/wonton-omp/skills/wonton-help/SKILL.md

ENV HOME=/data/agent/home \
    WONTON_ACP_SOCKET=/data/run/acp.sock \
    WONTON_AGENT_WORKSPACE=/workspace

USER 65532:65532
ENTRYPOINT ["/usr/local/bin/wonton-omp-agent"]
