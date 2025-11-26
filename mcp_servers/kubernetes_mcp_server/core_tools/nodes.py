"""
Kubernetes MCP Server - core tools: nodes

提供节点相关只读与监测能力：
- nodes_top：通过 metrics.k8s.io/v1beta1 获取节点 CPU/内存用量（需部署 Metrics Server）
- nodes_stats_summary：通过 apiserver→kubelet Summary API 获取节点详细资源统计（含 CPU/内存/文件系统/网络等）
- nodes_log：通过 apiserver→kubelet logs 代理获取节点日志（如 kubelet、kube-proxy 或指定日志文件路径）

注意：
- 所有能力均为只读；如需进一步扩展请在只读与禁破坏开关下审慎添加。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

# 共享 FastMCP 实例
from .. import mcp  # type: ignore

# Kubernetes Python 客户端
_K8S_IMPORT_ERROR = None
try:
    from kubernetes import client as k8s_client  # type: ignore
    from kubernetes import config as k8s_config  # type: ignore
except Exception as _e:  # pragma: no cover
    _K8S_IMPORT_ERROR = _e
    k8s_client = None  # type: ignore
    k8s_config = None  # type: ignore


def _ensure_k8s_available() -> None:
    if _K8S_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Kubernetes Python 客户端未安装，请在环境中安装 `kubernetes` 包。"
        )


def _api_clients(context: Optional[str]) -> Dict[str, Any]:
    """
    返回常用 API 客户端：
    - core_v1: CoreV1Api（用于 kubelet 代理）
    - custom_api: CustomObjectsApi（用于 metrics.k8s.io）
    """
    _ensure_k8s_available()
    try:
        if context:
            k8s_config.load_kube_config(context=context)
        else:
            k8s_config.load_kube_config()
    except Exception:
        k8s_config.load_incluster_config()
    api_client = k8s_client.ApiClient()
    return {
        "core_v1": k8s_client.CoreV1Api(api_client),
        "custom_api": k8s_client.CustomObjectsApi(api_client),
    }


@mcp.tool(
    description="List the resource consumption (CPU/memory) for Nodes via metrics API (v1 fallback to v1beta1)"
)
def nodes_top(
    name: Optional[str] = Field(default=None, description="指定节点名称进行过滤"),
    label_selector: Optional[str] = Field(
        default=None,
        description="以标签选择器过滤节点（例如 'node-role.kubernetes.io/worker='）",
    ),
    context: Optional[str] = Field(
        default=None, description="kubeconfig 上下文；默认当前上下文"
    ),
) -> List[Dict[str, Any]]:
    """
    优先尝试 metrics.k8s.io v1（若可用），否则回退到 v1beta1。
    返回示例（简化）：
    [
      {"name":"worker-1","usage":{"cpu":"50m","memory":"1024Mi"}, "timestamp":"...", "window":"..."},
      ...
    ]
    """
    apis = _api_clients(context)
    custom_api: k8s_client.CustomObjectsApi = apis["custom_api"]

    group = "metrics.k8s.io"
    versions = ["v1", "v1beta1"]
    plural = "nodes"

    last_error: Optional[Exception] = None
    data: Dict[str, Any] = {}
    for version in versions:
        try:
            # GET /apis/metrics.k8s.io/{version}/nodes
            data = custom_api.list_cluster_custom_object(
                group=group,
                version=version,
                plural=plural,
                label_selector=label_selector,
            )
            last_error = None
            break
        except Exception as e:
            last_error = e
            continue

    if last_error is not None and not data:
        raise RuntimeError(
            f"无法获取节点监控指标（metrics.k8s.io v1/v1beta1 均不可用，可能未部署 Metrics Server）：{last_error}"
        ) from last_error

    items = data.get("items", []) if isinstance(data, dict) else []
    out: List[Dict[str, Any]] = []
    for it in items:
        meta = (it or {}).get("metadata", {})
        usage = (it or {}).get("usage", {})
        ts = (it or {}).get("timestamp")
        win = (it or {}).get("window")
        entry = {
            "name": meta.get("name"),
            "usage": usage,
            "timestamp": ts,
            "window": win,
        }
        if name and entry["name"] != name:
            continue
        out.append(entry)
    return out


def _resolve_log_path(query: str) -> str:
    """
    将用户友好的 query 转换为 kubelet 代理路径：
    - 'kubelet' => 'logs/kubelet.log'
    - 'kube-proxy' => 'logs/kube-proxy.log'
    - 以 '/' 开头的绝对文件路径 => 'logs{absolute_path}'（例如 '/var/log/kubelet.log' => 'logs/var/log/kubelet.log'）
    - 其他 => 'logs/{query}'（相对路径或文件名）
    """
    q = (query or "").strip()
    if q == "kubelet":
        return "logs/kubelet.log"
    if q == "kube-proxy":
        return "logs/kube-proxy.log"
    if q.startswith("/"):
        return f"logs{q}"
    return f"logs/{q}"


@mcp.tool(description="Get logs from a Kubernetes node via apiserver proxy to kubelet")
def nodes_log(
    name: str = Field(description="节点名称"),
    query: str = Field(
        description="日志来源或文件路径：'kubelet'、'kube-proxy' 或 '/var/log/xxx.log' 等"
    ),
    tailLines: int = Field(
        default=0,
        description="尾部行数（若 kubelet 支持，则作为附加参数；默认 0 表示全部）",
    ),
    context: Optional[str] = Field(
        default=None, description="kubeconfig 上下文；默认当前上下文"
    ),
) -> str:
    """
    使用 CoreV1Api 的 node 代理：
      GET /api/v1/nodes/{name}/proxy/{path}

    注意：不同集群的 kubelet 代理可用性与日志路径可能存在差异；本实现提供通用路径映射，并在包含查询参数失败时回退到不带查询参数。
    """
    apis = _api_clients(context)
    core_v1: k8s_client.CoreV1Api = apis["core_v1"]
    path = _resolve_log_path(query)

    # 优先尝试带 tailLines 参数（若提供）
    final_path = path if tailLines <= 0 else f"{path}?tailLines={tailLines}"
    try:
        resp = core_v1.connect_get_node_proxy_with_path(name=name, path=final_path)
        return resp if isinstance(resp, str) else str(resp)
    except Exception as e1:
        # 回退到不带查询参数
        try:
            resp = core_v1.connect_get_node_proxy_with_path(name=name, path=path)
            return resp if isinstance(resp, str) else str(resp)
        except Exception as e2:
            raise RuntimeError(
                f"获取节点日志失败（name={name}, path={path}），尝试带/不带查询参数均失败：{e1} | {e2}"
            ) from e2


@mcp.tool(
    description="Get detailed resource stats from a Kubernetes node via kubelet Summary API"
)
def nodes_stats_summary(
    name: str = Field(description="节点名称"),
    context: Optional[str] = Field(
        default=None, description="kubeconfig 上下文；默认当前上下文"
    ),
) -> Dict[str, Any]:
    """
    kubelet Summary API：
      GET /api/v1/nodes/{name}/proxy/stats/summary

    返回字典结构，包含 node/pod/container 层面的 CPU/Memory/FS/Network 等度量。
    """
    apis = _api_clients(context)
    core_v1: k8s_client.CoreV1Api = apis["core_v1"]

    try:
        resp = core_v1.connect_get_node_proxy_with_path(name=name, path="stats/summary")
    except Exception as e:
        raise RuntimeError(f"获取节点 Summary 失败（name={name}）：{e}") from e

    # 返回 JSON 字符串或对象；多数实现返回 JSON 文本
    # 统一转为字典
    if isinstance(resp, dict):
        return resp
    try:
        import json as _json

        return _json.loads(resp)  # type: ignore
    except Exception:
        # 返回原始字符串（不可解析时）
        return {"raw": resp}
