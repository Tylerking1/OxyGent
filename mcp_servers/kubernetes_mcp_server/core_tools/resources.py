"""
Kubernetes MCP Server - core tools: generic resources

- resources_list：按 apiVersion/kind（可选 namespace/labelSelector）列出资源
- resources_get：按 apiVersion/kind/name（可选 namespace）获取单个资源
- resources_create_or_update：接收 JSON/YAML 文本，解析为对象后：存在则 patch，不存在则 create
- resources_delete：按 apiVersion/kind/name（可选 namespace）删除资源

设计要点
- 使用 Kubernetes Python Client 的 DynamicClient 动态分派各组/版本/类型
- 尽可能保持与服务端 apply/patch 一致的错误语义（字段管理器/冲突时的提示）
- 非破坏模式与禁删/禁更新保护：通过包级安全开关生效
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from pydantic import Field

# 共享 MCP 实例与安全开关
from .. import mcp, is_read_only, is_disable_destructive  # type: ignore

# 依赖：Kubernetes Python 客户端（包含 dynamic）
_K8S_IMPORT_ERROR = None
try:
    from kubernetes import client as k8s_client  # type: ignore
    from kubernetes import config as k8s_config  # type: ignore
    from kubernetes.dynamic import DynamicClient  # type: ignore
except Exception as _e:  # pragma: no cover
    _K8S_IMPORT_ERROR = _e
    k8s_client = None  # type: ignore
    k8s_config = None  # type: ignore
    DynamicClient = None  # type: ignore

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


def _ensure_k8s_available() -> None:
    if _K8S_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Kubernetes Python 客户端未安装，请在环境中安装 `kubernetes` 包。"
        )


def _api_dyn(context: Optional[str]) -> DynamicClient:
    """
    返回 DynamicClient；优先 kubeconfig，其次 in-cluster。
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
    return DynamicClient(api_client)  # type: ignore


def _get_resource(dyn: DynamicClient, apiVersion: str, kind: str):
    """
    解析并返回动态资源对象；异常统一抛出。
    """
    try:
        return dyn.resources.get(api_version=apiVersion, kind=kind)
    except Exception as e:
        raise RuntimeError(
            f"无法解析资源类型（apiVersion={apiVersion}, kind={kind}）：{e}"
        ) from e


def _sanitize(obj: Any) -> Dict[str, Any]:
    """
    将任意 Kubernetes 对象转为字典；DynamicClient 返回已是字典，保持幂等。
    """
    if isinstance(obj, dict):
        return obj
    # Fallback：若存在元数据对象等，尝试通过 ApiClient sanitize
    try:
        ac = k8s_client.ApiClient()
        return ac.sanitize_for_serialization(obj)  # type: ignore
    except Exception:
        return json.loads(json.dumps(obj, default=str))


def _mask_secret(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    对 Secret 对象进行敏感字段掩码处理：data/stringData 的值统一替换为 "***"。
    非 Secret 对象原样返回。
    """
    try:
        if not isinstance(obj, dict):
            return obj
        if obj.get("kind") != "Secret":
            return obj
        if isinstance(obj.get("data"), dict):
            obj["data"] = {k: "***" for k in obj["data"].keys()}
        if isinstance(obj.get("stringData"), dict):
            obj["stringData"] = {k: "***" for k in obj["stringData"].keys()}
    except Exception:
        # 掩码过程中出现异常时，不阻断主流程
        return obj
    return obj


@mcp.tool(
    description="List Kubernetes resources and objects by apiVersion/kind (optional: namespace, labelSelector)"
)
def resources_list(
    apiVersion: str = Field(description="例如 'v1','apps/v1','networking.k8s.io/v1'"),
    kind: str = Field(description="例如 'Pod','Service','Deployment','Ingress'"),
    namespace: Optional[str] = Field(
        default=None, description="命名空间（集群级资源忽略）"
    ),
    labelSelector: Optional[str] = Field(
        default=None, description="标签选择器（例如 'app=myapp,env=prod'）"
    ),
    context: Optional[str] = Field(
        default=None, description="kubeconfig 上下文；默认当前上下文"
    ),
) -> List[Dict[str, Any]]:
    dyn = _api_dyn(context)
    res = _get_resource(dyn, apiVersion, kind)
    try:
        if namespace:
            lst = res.list(namespace=namespace, label_selector=labelSelector)
        else:
            # 集群级或所有命名空间
            lst = res.list(label_selector=labelSelector)
    except Exception as e:
        raise RuntimeError(f"列出资源失败：{e}") from e

    items = lst.get("items", []) if isinstance(lst, dict) else []
    sanitized = [item if isinstance(item, dict) else _sanitize(item) for item in items]
    return [_mask_secret(i) for i in sanitized]


@mcp.tool(
    description="Get a Kubernetes resource by apiVersion/kind/name (optional: namespace)"
)
def resources_get(
    apiVersion: str = Field(description="例如 'apps/v1'"),
    kind: str = Field(description="例如 'Deployment'"),
    name: str = Field(description="资源名称"),
    namespace: Optional[str] = Field(
        default=None, description="命名空间（集群级资源忽略）"
    ),
    context: Optional[str] = Field(
        default=None, description="kubeconfig 上下文；默认当前上下文"
    ),
) -> Dict[str, Any]:
    dyn = _api_dyn(context)
    res = _get_resource(dyn, apiVersion, kind)
    try:
        if namespace:
            obj = res.get(name=name, namespace=namespace)
        else:
            # 对于集群级资源，忽略 namespace
            obj = res.get(name=name)
    except Exception as e:
        raise RuntimeError(f"获取资源失败：{e}") from e
    return _mask_secret(obj if isinstance(obj, dict) else _sanitize(obj))


@mcp.tool(
    description="Create or update a Kubernetes resource from YAML/JSON (server-side patch on exists)"
)
def resources_create_or_update(
    resource: str = Field(
        description="资源对象内容（YAML 或 JSON 字符串），需包含 apiVersion/kind/metadata 等顶级字段"
    ),
    namespace: Optional[str] = Field(
        default=None,
        description="命名空间（若 resource.metadata.namespace 未提供时可作为默认值）",
    ),
    context: Optional[str] = Field(
        default=None, description="kubeconfig 上下文；默认当前上下文"
    ),
) -> Dict[str, Any]:
    # 安全保护：只读或禁破坏时拒绝写操作
    if is_read_only() or is_disable_destructive():
        raise RuntimeError("写操作被禁止：当前处于只读或禁破坏模式")

    # 解析输入文本为对象
    obj: Dict[str, Any]
    try:
        if yaml is not None:
            obj = yaml.safe_load(resource)  # type: ignore
            if not isinstance(obj, dict):
                raise ValueError("解析结果不是对象字典")
        else:
            obj = json.loads(resource)
            if not isinstance(obj, dict):
                raise ValueError("解析结果不是对象字典")
    except Exception as e:
        raise RuntimeError(f"解析资源内容失败（期望 YAML/JSON 字符串）：{e}") from e

    apiVersion = obj.get("apiVersion")
    kind = obj.get("kind")
    meta = obj.get("metadata") or {}
    name = meta.get("name")
    ns = meta.get("namespace") or namespace

    if not apiVersion or not kind or not name:
        raise RuntimeError("资源缺少必要字段：apiVersion/kind/metadata.name")
    dyn = _api_dyn(context)
    res = _get_resource(dyn, apiVersion, kind)

    # create or patch（优先 patch 合并）
    try:
        # 先尝试获取以判断存在性
        exists = None
        try:
            exists = res.get(name=name, namespace=ns) if ns else res.get(name=name)
        except Exception:
            exists = None

        if exists:
            # 使用 merge patch 更新（通用安全，避免覆盖未知字段）
            patched = (
                res.patch(
                    name=name,
                    namespace=ns,
                    body=obj,
                    content_type="application/merge-patch+json",
                )
                if ns
                else res.patch(
                    name=name,
                    body=obj,
                    content_type="application/merge-patch+json",
                )
            )
            return _mask_secret(
                patched if isinstance(patched, dict) else _sanitize(patched)
            )
        else:
            created = (
                res.create(
                    body=obj,
                    namespace=ns,
                )
                if ns
                else res.create(body=obj)
            )
            return _mask_secret(
                created if isinstance(created, dict) else _sanitize(created)
            )
    except Exception as e:
        raise RuntimeError(f"创建/更新资源失败：{e}") from e


@mcp.tool(
    description="Delete a Kubernetes resource by apiVersion/kind/name (optional: namespace)"
)
def resources_delete(
    apiVersion: str = Field(description="例如 'v1','apps/v1'"),
    kind: str = Field(description="例如 'Pod','Deployment'"),
    name: str = Field(description="资源名称"),
    namespace: Optional[str] = Field(
        default=None, description="命名空间（集群级资源忽略）"
    ),
    context: Optional[str] = Field(
        default=None, description="kubeconfig 上下文；默认当前上下文"
    ),
) -> Dict[str, Any]:
    # 安全保护：只读或禁破坏时拒绝删除
    if is_read_only() or is_disable_destructive():
        raise RuntimeError("删除操作被禁止：当前处于只读或禁破坏模式")

    dyn = _api_dyn(context)
    res = _get_resource(dyn, apiVersion, kind)
    try:
        deleted = (
            res.delete(name=name, namespace=namespace)
            if namespace
            else res.delete(name=name)
        )
        return _mask_secret(
            deleted if isinstance(deleted, dict) else _sanitize(deleted)
        )
    except Exception as e:
        raise RuntimeError(f"删除资源失败：{e}") from e
