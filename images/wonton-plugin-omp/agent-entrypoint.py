#!/usr/bin/env python3
"""omp 的 ACP 入口：配置模型，把 unix socket 转发到 `omp acp` 的标准输入输出。

omp 只说 ACP stdio，桥在另一个容器里，所以由这里起 socket 并在前面转发。omp 退出时容器跟着退出，
桥按“Agent 未就绪”重试，不重启成假成功。

模型网关是可选的：三个模型变量都有值时把网关写进 omp 配置（密钥只引用变量名）；缺任何一个就按
“没接上网关”处理，去掉之前写进去的网关配置（网关被卸掉后不能还指着旧地址），让 omp 用它自己的
官方登录或用户已存的凭据。每次启动都重新判断，不只在首次初始化时写死。
"""
import asyncio
import json
import os
import signal
import socket
from pathlib import Path

SOCKET = Path(os.environ.get("WONTON_ACP_SOCKET", "/data/run/acp.sock"))
# 桥的约定：登录控制 socket 是 ACP socket 换掉最后一个后缀。
LOGIN_SOCKET = SOCKET.with_suffix(".login.sock")
WORKSPACE = Path(os.environ.get("WONTON_AGENT_WORKSPACE", "/workspace"))
AGENT_HOME = Path(os.environ.get("HOME", "/data/agent/home"))
CONFIG_DIR = AGENT_HOME / ".omp" / "agent"
GATEWAY_PROVIDER = "wonton"


async def relay(client: socket.socket, process: asyncio.subprocess.Process) -> None:
    loop = asyncio.get_running_loop()

    async def socket_to_agent() -> None:
        while True:
            data = await loop.sock_recv(client, 512 * 1024)
            if not data:
                return
            if process.stdin:
                process.stdin.write(data)
                await process.stdin.drain()

    async def agent_to_socket() -> None:
        while True:
            if process.stdout is None:
                return
            data = await process.stdout.read(512 * 1024)
            if not data:
                return
            await loop.sock_sendall(client, data)

    tasks = [asyncio.create_task(socket_to_agent()), asyncio.create_task(agent_to_socket())]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        task.result()


SKILL_SOURCE = Path("/usr/local/share/wonton-omp/skills")


def install_skills() -> None:
    # HOME 是挂载点，包里的 configs 挂不进来；每次启动按镜像里的版本覆盖，跟着插件版本走。
    for source in SKILL_SOURCE.rglob("*"):
        if not source.is_file():
            continue
        target = AGENT_HOME / ".agents" / "skills" / source.relative_to(SKILL_SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())


def _read_json(path: Path) -> dict | None:
    try:
        text = path.read_text()
    except FileNotFoundError:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} 不是合法 JSON，没法安全地改：{error}") from error
    return value if isinstance(value, dict) else None


def remove_gateway() -> None:
    """去掉之前写进去的网关 provider 和指向它的模型角色，其余内容保留；文件空了就删掉。"""
    models_path = CONFIG_DIR / "models.yml"
    models = _read_json(models_path)
    providers = models.get("providers") if isinstance(models, dict) else None
    if isinstance(providers, dict) and GATEWAY_PROVIDER in providers:
        del providers[GATEWAY_PROVIDER]
        if providers:
            models_path.write_text(json.dumps(models))
        else:
            models_path.unlink()

    config_path = CONFIG_DIR / "config.yml"
    settings = _read_json(config_path)
    roles = settings.get("modelRoles") if isinstance(settings, dict) else None
    if isinstance(roles, dict):
        kept = {
            role: model
            for role, model in roles.items()
            if not (isinstance(model, str) and model.startswith(f"{GATEWAY_PROVIDER}/"))
        }
        if kept != roles:
            if kept:
                settings["modelRoles"] = kept
                config_path.write_text(json.dumps(settings))
            else:
                settings.pop("modelRoles", None)
                if settings:
                    config_path.write_text(json.dumps(settings))
                else:
                    config_path.unlink()


def configure_model() -> None:
    # omp 不读 OPENAI_BASE_URL/OPENAI_MODEL；密钥只以环境变量名引用，不把值写进配置。
    model = os.environ.get("OPENAI_MODEL", "").strip()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if model and base_url and api_key:
        provider = {
            "baseUrl": base_url,
            "api": "openai-completions",
            "apiKey": "OPENAI_API_KEY",
            "models": [{"id": model}],
        }
        (CONFIG_DIR / "models.yml").write_text(json.dumps({"providers": {GATEWAY_PROVIDER: provider}}))
        selector = f"{GATEWAY_PROVIDER}/{model}"
        settings = {"modelRoles": {role: selector for role in ("default", "smol", "slow", "plan")}}
        (CONFIG_DIR / "config.yml").write_text(json.dumps(settings))
    else:
        remove_gateway()


async def _send_frame(client: socket.socket, frame: dict) -> None:
    await asyncio.get_running_loop().sock_sendall(client, (json.dumps(frame, ensure_ascii=False) + "\n").encode())


async def serve_login(listener: socket.socket) -> None:
    """终端类登录：桥连这个 socket，入口启动 omp 的官方登录进程并按行转发。

    协议（与桥 login/terminal.rs 约定）：桥先发一行 JSON {"methodId","args","env"}；之后桥发的每行
    文本写入登录进程 stdin；登录进程的 stdout/stderr 每行回 {"out"}/{"err"}，结束时回 {"exit": 数字}，
    退出码 0 才算成功。
    """
    loop = asyncio.get_running_loop()
    while True:
        client, _ = await loop.sock_accept(listener)
        try:
            await relay_login(client, loop)
        except (ValueError, OSError) as error:
            # 单次登录失败不拖垮入口，把原因按协议回给桥。
            for frame in ({"err": f"登录转发失败：{error}"}, {"exit": 1}):
                try:
                    await _send_frame(client, frame)
                except OSError:
                    break
        finally:
            client.close()


async def relay_login(client: socket.socket, loop: asyncio.AbstractEventLoop, command=None) -> None:
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), client.makefile("rb"))
    request_line = await reader.readline()
    if not request_line:
        return
    request = json.loads(request_line)
    if command is None:
        # omp 只有一种终端登录方式（methodId terminal）：它的默认形态是全屏 TUI，行式转发跑不起来。
        # omp login 是同一套官方登录的行式形态（选 provider、打印链接、收授权码和 key 都走 stdout/stdin），
        # 在聊天里能完成；凭据写进 HOME 下的 agent.db，容器重建后还在。method 的 args 是 TUI 的开关，
        # 这里不带。
        if request.get("methodId") != "terminal":
            raise ValueError(f"不支持的登录方式 {request.get('methodId')!r}")
        command = ["/usr/local/bin/omp", "login"]
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **request.get("env", {})},
        cwd=WORKSPACE,
    )
    stdin = process.stdin

    async def pump_output(stream: asyncio.StreamReader, key: str) -> None:
        while line := await stream.readline():
            await _send_frame(client, {key: line.decode(errors="replace").rstrip("\n")})

    async def pump_input() -> None:
        assert stdin is not None
        while line := await reader.readline():
            stdin.write(line)
            await stdin.drain()

    stdout_task = asyncio.create_task(pump_output(process.stdout, "out"))
    stderr_task = asyncio.create_task(pump_output(process.stderr, "err"))
    input_task = asyncio.create_task(pump_input())
    exit_task = asyncio.create_task(process.wait())
    done, _ = await asyncio.wait({exit_task, input_task}, return_when=asyncio.FIRST_COMPLETED)
    if input_task in done:
        # 桥断开（取消、超时、桥退出）：登录进程可能还在等 stdin，必须结束并收回，
        # 否则串行的 serve_login 会一直卡在这次登录上。
        stdin.close()
        try:
            code = await asyncio.wait_for(process.wait(), 2)
        except asyncio.TimeoutError:
            process.terminate()
            try:
                code = await asyncio.wait_for(process.wait(), 2)
            except asyncio.TimeoutError:
                process.kill()
                code = await process.wait()
    else:
        code = exit_task.result()
    input_task.cancel()
    await asyncio.gather(stdout_task, stderr_task, exit_task, return_exceptions=True)
    try:
        await _send_frame(client, {"exit": code})
    except OSError:
        pass


async def main() -> None:
    for directory in (AGENT_HOME, WORKSPACE, SOCKET.parent):
        directory.mkdir(parents=True, exist_ok=True)
    install_skills()
    configure_model()
    for path in (SOCKET, LOGIN_SOCKET):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(SOCKET))
    os.chmod(SOCKET, 0o600)
    listener.listen(8)
    listener.setblocking(False)
    login_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    login_listener.bind(str(LOGIN_SOCKET))
    os.chmod(LOGIN_SOCKET, 0o600)
    login_listener.listen(2)
    login_listener.setblocking(False)
    login_task = asyncio.create_task(serve_login(login_listener))
    process = await asyncio.create_subprocess_exec(
        "/usr/local/bin/omp",
        "acp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=None,
        cwd=WORKSPACE,
    )
    loop = asyncio.get_running_loop()
    try:
        while process.returncode is None:
            accept_task = asyncio.create_task(loop.sock_accept(listener))
            exit_task = asyncio.create_task(process.wait())
            done, pending = await asyncio.wait(
                [accept_task, exit_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if exit_task in done:
                break
            client, _ = accept_task.result()
            client.setblocking(False)
            try:
                await relay(client, process)
            finally:
                client.close()
    finally:
        if process.returncode is None:
            process.send_signal(signal.SIGTERM)
        await process.wait()
        login_task.cancel()
        await asyncio.gather(login_task, return_exceptions=True)
        listener.close()
        login_listener.close()
        for path in (SOCKET, LOGIN_SOCKET):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    asyncio.run(main())
