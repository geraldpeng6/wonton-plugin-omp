# omp

开发流程见[插件开发指南](https://github.com/geraldpeng6/wonton-docs/blob/main/develop.md)。

omp 是住在云吞里的 Agent：用核心分配的 Matrix 身份和主人聊天，经 Wonton MCP 总线调用工具。
它只说 ACP，插件里自带一个固定的 Wonton ACP 桥。

## 模型

有模型网关时，模型调用默认走网关，不用账号，也不用填任何 key。网关是可选的：没接上网关时 Agent 照样起来，
在聊天里发 `/wonton login` 选登录方式：模型账号（OAuth 链接发进聊天，浏览器里授权后把跳转地址或授权码发回来；
设备码流程直接在页面输码）或直接填模型的 key。登录态在数据目录里，容器重建后还在。

omp 靠模型自己决定调工具、跑命令，对模型比一般聊天挑。插件 v0.1.0 的真实冒烟（2026-11-06，同一份插件，默认路由指向不同模型）：

| 模型 | 结果 |
| --- | --- |
| gpt-6.1-sol | 全部通过：聊天、经总线调工具、确认卡片的同意和拒绝、打断、重启后续聊 |
| gpt-6-astra | 不稳：一轮能聊但不主动调 `wonton__list_plugins`，只回答自己的名字；另一轮上游断线，确认卡片和打断等不到回复 |
| DeepSeek-4.1-Flash | 失败：上游排队，一轮 ACP 超时，确认卡片和续聊都没过 |
| glm-5.3-flashx | 失败：上游 402 余额不足，只有不调模型的几项通过 |

后三行里有的是上游当时的额度和负载，不全是模型能力；结论是默认路由要指向调工具可靠、上游稳定的模型。

## 图标

`icon.svg` 是 omp 的官方标志，等比放在 `#111111` 底上，原样使用。来源、许可证和商标说明见 [NOTICE](NOTICE)。

## 先跑起来

```bash
scripts/dev.sh up
scripts/dev.sh install
```

`up` 在本机起一套云吞并打印它的地址，用 `scripts/dev.sh token` 输出的用户令牌登录；`install` 列出插件要的权限，确认后
装上。插件没有网页：装好以后核心在聊天列表里建好和它的加密私聊，在那里和它说话；App 或 `scripts/dev.sh pair` 把它加进
客户端。

`docker-compose.yml` 的两个镜像按摘要固定：桥是主仓库发布的 `ghcr.io/geraldpeng6/wonton-acp-bridge`，直接拉取；agent 是
`images/wonton-plugin-omp/` 构建的。本地开发前先按下面的“构建镜像”把 agent 构建出来并写上本地的摘要；发布以后换成发布
版本的摘要。

## 构建镜像

```bash
docker build -t ghcr.io/geraldpeng6/wonton-plugin-omp:0.1.0 -f images/wonton-plugin-omp/Dockerfile images/wonton-plugin-omp
```

构建出来的是本地镜像，`docker image inspect -f '{{.Id}}'` 就是要写回 compose 的摘要。桥的 Dockerfile 在主仓库，
`scripts/publish.sh` 不会动它。

## 仓库里有什么

| 路径 | 内容 |
| --- | --- |
| `docker-compose.yml` | 插件本身：compose 加上 `x-wonton` 清单 |
| `icon.svg` | 商店图标，来源和许可证见 `NOTICE` |
| `images/wonton-plugin-omp/` | Agent 镜像：omp 的 Dockerfile、ACP 入口和上游许可证，不在插件包里 |
| `screenshots/` | 商店详情页里的截图 |
| `scripts/check.sh` | 检查插件包，规则和安装时一样 |
| `scripts/dev.sh` | 开发环境：起一套云吞，装、重装、卸载插件，看日志 |
| `scripts/smoke-probes.sh` | `scripts/dev.sh smoke` 对这个插件逐项的探测 |
| `.github/workflows/publish.yml` | 在 Actions 的机器上执行发布，镜像用 `GITHUB_TOKEN` 推送，本机不用登录镜像仓库 |
| `AGENTS.md` | 给人和 AI 编程代理的规则 |
| `LICENSE`、`NOTICE` | 插件许可证、官方标志与上游来源的许可和商标声明 |
