"""
Kubernetes MCP Server - core tools: pods

提供与 Pod 相关的常用只读能力：
- pods_list：列出所有命名空间的 Pods
- pods_list_in_namespace：列出指定命名空间的 Pods
- pods_get：获取指定 Pod 的完整对象
- pods_log：获取 Pod 日志（支持容器选择、previous、tail）
- pods_exec：在 Pod 容器内执行命令并返回输出
- pods_top：从 metrics.k8s.io 读取 Pod 资源使用情况（需部署 Metrics Server）

注意：
- 这里仅实现“只读/非破坏”能力；删除/创建等写操作后续按安全开关引入。
- 支持可选 context 参数以选择 kubeconfig 上下文；未提供时使用当前上下文/集群内配置。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from pydantic import Field

# 共享 FastMCP 实例与安全开关
from .. import mcp  # type: ignore

# 尝试导入 Kubernetes Python 客户端
_K8S_IMPORT_ERROR = None
try:
    from kubernetes import client as k8s_client  # type: ignore
    from kubernetes import config as k8s_config  # type: ignore
    from kubernetes.stream import stream as k8s_stream  # type: ignore
except Exception as _e:  # pragma: no cover
    _K8S_IMPORT_ERROR = _e
    k8s_client = None  # type: ignore
    k8s_config = None  # type: ignore
    k8s_stream = None  # type: ignore


def _ensure_k8s_available() -> None:
    if _K8S_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Kubernetes Python 客户端未安装，请在环境中安装 `kubernetes` 包。"
        )


def _load_kube_config(context: Optional[str] = None) -> k8s_client.ApiClient:
    """
    优先从 kubeconfig（KUBECONFIG 或 ~/.kube/config）加载；失败时尝试 in-cluster。
    """
    _ensure_k8s_available()
    try:
        # KUBECONFIG or default ~/.kube/config
        if context:
            k8s_config.load_kube_config(context=context)
        else:
            k8s_config.load_kube_config()
    except Exception:
        # in-cluster fallback
        k8s_config.load_incluster_config()
    return k8s_client.ApiClient()


def _api_clients(context: Optional[str]) -> Dict[str, Any]:
    """
    返回常用 API 客户端：
    - core_v1: CoreV1Api
    - custom_api: CustomObjectsApi（用于 metrics.k8s.io 等）
    - api_client: 原始 ApiClient（sanitize 序列化）
    """
    api_client = _load_kube_config(context=context)
    return {
        "core_v1": k8s_client.CoreV1Api(api_client),
        "custom_api": k8s_client.CustomObjectsApi(api_client),
        "api_client": api_client,
    }


def _pod_summary(item: Any) -> Dict[str, Any]:
    meta = getattr(item, "metadata", None)
    spec = getattr(item, "spec", None)
    status = getattr(item, "status", None)
    return {
        "name": getattr(meta, "name", None),
        "namespace": getattr(meta, "namespace", None),
        "phase": getattr(status, "phase", None),
        "nodeName": getattr(spec, "node_name", None) if spec else None,
        "hostIP": getattr(status, "host_ip", None),
        "podIP": getattr(status, "pod_ip", None),
        "startTime": getattr(status, "start_time", None).isoformat()
        if getattr(status, "start_time", None)
        else None,
        "labels": dict(getattr(meta, "labels", {}) or {}) if meta else {},
    }


@mcp.tool(
    description="List all the Kubernetes pods in the current cluster from all namespaces"
)
def pods_list(
    labelSelector: Optional[str] = Field(
        default=None, description="Kubernetes label selector, e.g. 'app=myapp,env=prod'"
    ),
    context: Optional[str] = Field(
        default=None, description="Kubeconfig context name; defaults to current context"
    ),
) -> List[Dict[str, Any]]:
    _ensure_k8s_available()
    apis = _api_clients(context)
    core_v1: k8s_client.CoreV1Api = apis["core_v1"]
    ret = core_v1.list_pod_for_all_namespaces(label_selector=labelSelector)
    return [_pod_summary(p) for p in ret.items or []]


@mcp.tool(description="List all the Kubernetes pods in the specified namespace")
def pods_list_in_namespace(
    namespace: str = Field(description="Namespace to list pods from"),
    labelSelector: Optional[str] = Field(
        default=None, description="Kubernetes label selector, e.g. 'app=myapp'"
    ),
    context: Optional[str] = Field(
        default=None, description="Kubeconfig context name; defaults to current context"
    ),
) -> List[Dict[str, Any]]:
    _ensure_k8s_available()
    apis = _api_clients(context)
    core_v1: k8s_client.CoreV1Api = apis["core_v1"]
    ret = core_v1.list_namespaced_pod(namespace=namespace, label_selector=labelSelector)
    return [_pod_summary(p) for p in ret.items or []]


@mcp.tool(description="Get a Kubernetes Pod by name in the provided namespace")
def pods_get(
    name: str = Field(description="Pod name"),
    namespace: str = Field(description="Namespace of the Pod"),
    context: Optional[str] = Field(
        default=None, description="Kubeconfig context name; defaults to current context"
    ),
) -> Dict[str, Any]:
    """
    为避免全集群扫描带来的性能与语义问题，必须提供 namespace。
    """
    _ensure_k8s_available()
    apis = _api_clients(context)
    core_v1: k8s_client.CoreV1Api = apis["core_v1"]
    api_client: k8s_client.ApiClient = apis["api_client"]

    obj = core_v1.read_namespaced_pod(name=name, namespace=namespace)
    return api_client.sanitize_for_serialization(obj)  # type: ignore


@mcp.tool(description="Get logs of a Kubernetes Pod")
def pods_log(
    name: str = Field(description="Pod name"),
    namespace: str = Field(description="Namespace of the Pod"),
    container: Optional[str] = Field(
        default=None, description="Container name in the Pod"
    ),
    previous: bool = Field(
        default=False, description="Return previous terminated container logs"
    ),
    tail: int = Field(
        default=100, description="Number of lines to retrieve from end; 0 to get all"
    ),
    context: Optional[str] = Field(
        default=None, description="Kubeconfig context name; defaults to current context"
    ),
) -> str:
    _ensure_k8s_available()
    apis = _api_clients(context)
    core_v1: k8s_client.CoreV1Api = apis["core_v1"]
    kwargs: Dict[str, Any] = {
        "name": name,
        "namespace": namespace,
        "previous": previous,
    }
    if container:
        kwargs["container"] = container
    if tail and tail > 0:
        kwargs["tail_lines"] = tail
    return core_v1.read_namespaced_pod_log(**kwargs)


@mcp.tool(
    description="Execute a command in a Kubernetes Pod container and return the output (combined stdout/stderr)"
)
def pods_exec(
    command: List[str] = Field(description="Command array, e.g. ['ls','-l','/']"),
    name: str = Field(description="Pod name"),
    namespace: str = Field(description="Namespace of the Pod"),
    container: Optional[str] = Field(
        default=None, description="Container name; default first container"
    ),
    context: Optional[str] = Field(
        default=None, description="Kubeconfig context name; defaults to current context"
    ),
) -> str:
    _ensure_k8s_available()
    apis = _api_clients(context)
    core_v1: k8s_client.CoreV1Api = apis["core_v1"]
    # 使用流式 exec；这里将 stdout/stderr 合并返回（非交互）
    resp = k8s_stream(
        core_v1.connect_get_namespaced_pod_exec,
        name,
        namespace,
        container=container,
        command=command,
        stderr=True,
        stdin=False,
        stdout=True,
        tty=False,
    )
    # stream(...) 返回字符串（非交互模式）
    return resp if isinstance(resp, str) else str(resp)


@mcp.tool(
    description="List the resource consumption (CPU/memory) for Pods via metrics API (v1 fallback to v1beta1)"
)
def pods_top(
    namespace: Optional[str] = Field(
        default=None,
        description="Namespace to get metrics from; all namespaces if omitted",
    ),
    name: Optional[str] = Field(
        default=None, description="Specific Pod name to filter"
    ),
    label_selector: Optional[str] = Field(
        default=None, description="Label selector to filter pods"
    ),
    context: Optional[str] = Field(
        default=None, description="Kubeconfig context name; defaults to current context"
    ),
) -> List[Dict[str, Any]]:
    """
    优先尝试 metrics.k8s.io v1（若可用），否则回退到 v1beta1。
    返回示例（简化）：
    [
      {"namespace":"default","name":"nginx-xxx","containers":[{"name":"nginx","usage":{"cpu":"5m","memory":"20Mi"}}], "timestamp":"...", "window":"..."},
      ...
    ]
    """
    _ensure_k8s_available()
    apis = _api_clients(context)
    custom_api: k8s_client.CustomObjectsApi = apis["custom_api"]

    group = "metrics.k8s.io"
    versions = ["v1", "v1beta1"]  # 优先 v1，失败回退 v1beta1
    plural = "pods"

    last_error: Optional[Exception] = None
    data: Dict[str, Any] = {}
    for version in versions:
        try:
            if namespace:
                # GET /apis/metrics.k8s.io/{version}/namespaces/{namespace}/pods
                data = custom_api.list_namespaced_custom_object(
                    group=group,
                    version=version,
                    namespace=namespace,
                    plural=plural,
                    label_selector=label_selector,
                )
            else:
                # GET /apis/metrics.k8s.io/{version}/pods
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
            f"无法获取 Pod 监控指标（metrics.k8s.io v1/v1beta1 均不可用，可能未部署 Metrics Server）：{last_error}"
        ) from last_error

    items = data.get("items", []) if isinstance(data, dict) else []
    out: List[Dict[str, Any]] = []
    for it in items:
        meta = (it or {}).get("metadata", {})
        spec = (it or {}).get("containers", [])
        ts = (it or {}).get("timestamp")
        win = (it or {}).get("window")
        entry = {
            "namespace": meta.get("namespace"),
            "name": meta.get("name"),
            "containers": [
                {"name": c.get("name"), "usage": c.get("usage")} for c in spec
            ],
            "timestamp": ts,
            "window": win,
        }
        if name and entry["name"] != name:
            continue
        out.append(entry)
    return out
