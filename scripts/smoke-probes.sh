# shellcheck shell=bash
# omp 是 Agent：没有网页入口、应用账号体系或插件自己的 MCP 服务。
# 通用插件冒烟只验证清单能装上；Matrix 加密私聊、模型回答和 Wonton MCP 在专项验收里实测。
export IDENTITY_NA=1
export SMOKE_NOTE="omp 没有网页入口、应用账号体系或插件自己的 MCP 服务；网页、用户身份、插件工具三项不适用。专项验收验证加密 Matrix 私聊、模型回答和 Wonton MCP 只读工具。"

marker_file() { # SMOKE_STATE 在套件里是状态目录（e2e 传的是标记文件本身），标记放对应路径
  if [[ -d "$SMOKE_STATE" ]]; then printf '%s' "$SMOKE_STATE/omp-marker"; else printf '%s' "${SMOKE_STATE}.marker"; fi
}

_omp_agent_container() { # 容器按核心打的标签找，不拼名字（钩子契约里没有 slug，data_write 又跑在实例名导出之前）
  local inst="${SMOKE_INSTANCE:-}" args=(--filter label=wonton.plugin=ai.omp.agent --filter label=wonton.service=agent)
  if [[ -z "$inst" && -n "${SMOKE_BASE:-}" ]]; then
    inst="${SMOKE_BASE#http://}"; inst="${inst%%.*}"
  fi
  [[ -z "$inst" ]] || args+=(--filter "label=wonton.instance=${inst//-/}")
  docker ps --format '{{.Names}}' "${args[@]}" | head -1
}

# 数据：Agent 的用户数据就是它的工作区（compose 里挂 Bot 数据目录的 workspace 卷，升级重装都保留）。
# Agent 的写入口是聊天里的工具调用，要真实模型；冒烟直接经 docker cp 在工作区放标记文件、重装后读回核对。
data_write() {
  local container marker tmp
  [[ -n "${SMOKE_STATE:-}" ]] || { echo "SMOKE_STATE 没设"; return 1; }
  container="$(_omp_agent_container)"
  [[ -n "$container" ]] || { echo "找不到 agent 容器（wonton.instance 标签）"; return 1; }
  marker="wonton-smoke-$(od -An -N4 -tx4 /dev/urandom | tr -d ' \n')"
  tmp="$(marker_file).upload"
  printf '%s' "$marker" >"$tmp" || return 1
  docker cp "$tmp" "$container:/workspace/wonton-smoke-marker" ||
    { echo "标记放不进工作区（容器 $container）"; rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  printf '%s' "$marker" >"$(marker_file)"
}

data_check() {
  local container marker out
  marker="$(cat "$(marker_file)" 2>/dev/null)" || { echo "没有 data_write 留下的标记"; return 1; }
  [[ -n "$marker" ]] || { echo "标记是空的"; return 1; }
  container="$(_omp_agent_container)"
  [[ -n "$container" ]] || { echo "找不到 agent 容器（wonton.instance 标签）"; return 1; }
  out="$(docker cp "$container:/workspace/wonton-smoke-marker" - 2>/dev/null | tar -xO)" ||
    { echo "工作区标记读不到（数据卷丢了？）"; return 1; }
  [[ "$out" == "$marker" ]] || { echo "标记对不上：期待 $marker，看到 $out"; return 1; }
}
