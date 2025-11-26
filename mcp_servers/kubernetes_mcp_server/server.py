"""
Kubernetes MCP Server - Entry Point

该入口对齐 OxyGent 现有 MCP 服务器风格，提供：
- 传输模式：stdio / sse / streamable-http
- 端口配置（SSE/Streamable HTTP）
- 工具集按需加载（config/core/helm），为非破坏模式等安全开关预留过滤点

后续步骤：
- 在 kubernetes/config_tools.py、kubernetes/core_tools/*、kubernetes/helm_tools.py 中实现具体工具
- server.py 按 toolsets 参数/环境变量进行模块化加载，实现只读/禁删等过滤
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from typing import List, Set

# 包级全局：共享 FastMCP 实例与安全开关
from . import mcp as pkg_mcp, is_read_only, is_disable_destructive  # type: ignore
from mcp.server.fastmcp import FastMCP


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser("kubernetes_mcp_server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.getenv("K8S_MCP_TRANSPORT", "stdio"),
        help="MCP transport mode: stdio / sse / streamable-http",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("K8S_MCP_PORT", "8000")),
        help="Server port for SSE/Streamable-HTTP (default: 8000)",
    )
    parser.add_argument(
        "--toolsets",
        type=str,
        default=os.getenv("K8S_MCP_TOOLSETS", "config,core,helm"),
        help="Comma-separated toolsets to enable: config,core,helm",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Run in read-only mode (remove destructive tools)",
    )
    parser.add_argument(
        "--disable-destructive",
        action="store_true",
        help="Disable destructive operations (delete/update) even if not fully read-only",
    )
    return parser.parse_args()


def _normalize_toolsets(toolsets_str: str) -> Set[str]:
    return {t.strip() for t in toolsets_str.split(",") if t.strip()}


def _rebind_mcp_for_network_transport(port: int) -> None:
    """
    在需要网络传输（sse/streamable-http）时，按指定端口重新绑定包级 mcp。
    确保工具模块在导入后共享同一个实例。
    """
    pkg = importlib.import_module(
        __name__.rsplit(".", 1)[0]
    )  # 包: frameworks.OxyGent.mcp_servers.kubernetes_mcp_server
    pkg.mcp = FastMCP(port=port)  # 重新绑定包级 mcp 实例
    # 同步到当前模块引用
    global pkg_mcp
    pkg_mcp = pkg.mcp


def _load_toolsets(
    selected: Set[str], readonly: bool, disable_destructive: bool
) -> None:
    """
    根据选择的工具集按需加载模块。
    注意：
    - 破坏性工具（删除/更新）应放在独立模块，便于根据 readonly/disable_destructive 过滤掉。
    - 当前为骨架阶段，先加载只读/通用模块，后续实现写操作时在此处做条件导入。
    """

    base_pkg = "mcp_servers.kubernetes_mcp_server"

    # config 组
    if "config" in selected:
        importlib.import_module(f"{base_pkg}.config_tools")
    # core 组
    if "core" in selected:
        # 只读/通用能力优先
        importlib.import_module(f"{base_pkg}.core_tools.pods")
        importlib.import_module(f"{base_pkg}.core_tools.resources")
        importlib.import_module(f"{base_pkg}.core_tools.events")
        importlib.import_module(f"{base_pkg}.core_tools.namespaces")
        importlib.import_module(f"{base_pkg}.core_tools.nodes")
        # 未来：如需写操作（create/update/delete），在 readonly/disable_destructive 条件下决定是否导入
        if not readonly and not disable_destructive:
            # 例如：importlib.import_module(f"{base_pkg}.core_tools.destructive")
            pass
    # helm 组
    if "helm" in selected:
        # 优先模板化路径（渲染→apply/uninstall），避免强依赖 helm 二进制
        importlib.import_module(f"{base_pkg}.helm_tools")
        # 若未来提供直接 helm_* 工具，需在无只读且未禁删时再加载
        # if not readonly and not disable_destructive:
        #     importlib.import_module(f"{base_pkg}.helm_cli_tools")


def main() -> None:
    args = _parse_args()
    selected = _normalize_toolsets(args.toolsets)

    # 计算安全开关（命令行优先，环境变量作为默认）
    readonly = bool(args.read_only or is_read_only())
    disable_destructive = bool(args.disable_destructive or is_disable_destructive())

    # 根据传输模式与端口重新绑定 MCP（网络模式需要端口）
    if args.transport in {"sse", "streamable-http"}:
        _rebind_mcp_for_network_transport(args.port)

    # 加载工具集（会触发各模块通过 @mcp.tool 装饰器进行工具注册）
    _load_toolsets(selected, readonly, disable_destructive)

    # 运行服务器
    print("[kubernetes_mcp_server] transport=", args.transport)
    print("[kubernetes_mcp_server] port=", args.port)
    print("[kubernetes_mcp_server] toolsets=", ",".join(sorted(selected)))
    print(
        "[kubernetes_mcp_server] readonly=",
        readonly,
        " disable_destructive=",
        disable_destructive,
    )
    pkg_mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
