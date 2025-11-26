"""
Kubernetes MCP Server - config toolset

提供只读的 kubeconfig 检视能力：
- configuration_contexts_list：列出所有上下文与对应 server，并标记当前上下文
- configuration_view：返回 kubeconfig 内容（默认最小化为当前上下文相关片段）

实现要点：
- 优先读取 KUBECONFIG（支持以 os.pathsep 分隔的多个路径，取第一个存在的文件）
- 无 PyYAML 时降级输出 JSON 字符串
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from pydantic import Field

# 共享 FastMCP 实例
from . import mcp  # type: ignore

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


def _first_existing_kubeconfig() -> Optional[str]:
    """
    返回第一个存在的 kubeconfig 路径：
    - 优先环境变量 KUBECONFIG（可包含多个路径，使用 os.pathsep 分隔）
    - 否则默认 ~/.kube/config
    """
    env_paths = os.getenv("KUBECONFIG", "")
    candidates: List[str] = []
    if env_paths.strip():
        for p in env_paths.split(os.pathsep):
            if p.strip():
                candidates.append(os.path.expanduser(p.strip()))
    else:
        candidates.append(os.path.expanduser("~/.kube/config"))

    for p in candidates:
        if os.path.exists(p) and os.path.isfile(p):
            return p
    return None


def _load_kubeconfig_content() -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    读取并解析 kubeconfig，优先使用 YAML 解析；失败则尝试 JSON。
    返回 (配置字典, 实际使用的文件路径)；找不到则 (None, None)。
    """
    path = _first_existing_kubeconfig()
    if not path:
        return None, None

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return None, path

    # 优先 YAML
    if yaml is not None:
        try:
            data = yaml.safe_load(raw) or {}
            if isinstance(data, dict):
                return data, path
        except Exception:
            pass

    # 退化 JSON
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data, path
    except Exception:
        pass

    return None, path


def _minify_kubeconfig(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    仅保留与 current-context 相关的 contexts/clusters/users 片段。
    未配置 current-context 时返回原始配置。
    """
    current = cfg.get("current-context")
    if not current:
        return cfg

    contexts = cfg.get("contexts", []) or []
    clusters = cfg.get("clusters", []) or []
    users = cfg.get("users", []) or []

    ctx = next((c for c in contexts if c.get("name") == current), None)
    if not ctx:
        return cfg

    cluster_name = (ctx.get("context") or {}).get("cluster")
    user_name = (ctx.get("context") or {}).get("user")

    out: Dict[str, Any] = {
        "apiVersion": cfg.get("apiVersion"),
        "kind": cfg.get("kind", "Config"),
        "current-context": current,
        "contexts": [ctx] if ctx else [],
        "clusters": [c for c in clusters if c.get("name") == cluster_name]
        if cluster_name
        else [],
        "users": [u for u in users if u.get("name") == user_name] if user_name else [],
    }
    return out


@mcp.tool(
    description="List all available context names and associated server urls from the kubeconfig file"
)
def configuration_contexts_list() -> List[Dict[str, Any]]:
    """
    输出示例：
    [
      {"name":"minikube","cluster":"minikube","server":"https://127.0.0.1:6443","current":true},
      {"name":"prod","cluster":"prod-cluster","server":"https://prod.example:6443","current":false}
    ]
    """
    cfg, path = _load_kubeconfig_content()
    if not cfg:
        return []

    contexts = cfg.get("contexts", []) or []
    clusters = cfg.get("clusters", []) or []
    current = cfg.get("current-context")

    result: List[Dict[str, Any]] = []
    for c in contexts:
        name = c.get("name")
        ctx = c.get("context") or {}
        cluster_name = ctx.get("cluster")
        server = None
        if cluster_name:
            for cl in clusters:
                if cl.get("name") == cluster_name:
                    server = (cl.get("cluster") or {}).get("server")
                    break
        result.append(
            {
                "name": name,
                "cluster": cluster_name,
                "server": server,
                "current": bool(name == current),
            }
        )
    return result


@mcp.tool(
    description="Get the current Kubernetes configuration content as a kubeconfig YAML"
)
def configuration_view(
    minified: bool = Field(
        default=True,
        description="Return a minified version (only current-context and related pieces) if True",
    ),
) -> str:
    """
    返回 YAML 字符串；当未安装 PyYAML 或解析失败时，返回 JSON 字符串。
    """
    cfg, path = _load_kubeconfig_content()
    if not cfg:
        # 结构化空结果不便于客户端消费，此处返回可读的 YAML 注释字符串，便于直接展示给用户
        return "# kubeconfig not found. Please set KUBECONFIG or create ~/.kube/config"

    out = _minify_kubeconfig(cfg) if minified else cfg

    if yaml is not None:
        try:
            return yaml.safe_dump(out, sort_keys=False)
        except Exception:
            pass
    # 退化为 JSON
    return json.dumps(out, indent=2, ensure_ascii=False)
