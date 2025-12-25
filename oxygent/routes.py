"""routes.py.

FastAPI routing layer for the OxyGent MAS service.

This module exposes several HTTP endpoints that support:
    * Health checks and root redirection
    * Retrieval of node‐level execution details stored in Elasticsearch
    * Proxying user requests to an LLM provider through the OxyGent agent stack
    * Lightweight persistence for scripted calls (save / list / load)

Every public callable is documented using **Google Python Style** docstrings so
that automatic documentation tooling such as *Sphinx napoleon* can render them
cleanly.

Typical usage example::

    # uvicorn main:app --reload
    curl http://localhost:8000/check_alive  #→ {"alive": 1}
"""

import json
import logging
import os
import re
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any

import aiofiles
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .config import Config
from .databases.db_es import JesEs, LocalEs
from .db_factory import DBFactory
from .oxy_factory import OxyFactory, SecurityError
from .schemas import OxyRequest, WebResponse
from .utils.data_utils import add_post_and_child_node_ids

logger = logging.getLogger(__name__)

router = APIRouter()


# Basic route to redirect to the web interface
@router.get("/")
def read_root():
    """Redirect the client to the bundled web front-end.

    Returns:
        fastapi.responses.RedirectResponse: HTTP 307 redirect to
        ``./web/index.html`` that ships with the service UI.
    """
    return RedirectResponse(url="./web/index.html")


@router.get("/check_alive")
def check_alive():
    """Health‑check endpoint.

    Returns:
        dict: ``{"alive": 1}`` when the service is running.
    """
    # Application health check endpoint
    return {"alive": 1}


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    datetime_str = datetime.now().strftime("%Y%m%d%H%M%S")
    upload_dir = os.path.join(Config.get_cache_save_dir(), "uploads", datetime_str)
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    pic_url = f"../static/{datetime_str}/{file.filename}"

    # Save file asynchronously
    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    # Return file path
    return WebResponse(data={"file_name": pic_url}).to_dict()


@router.get("/node")
async def get_node_info(item_id: str):
    """Retrieve execution-node details using its *node_id* or *trace_id*.

    Args:
        item_id: Either a node identifier or a trace identifier. If the input
            is a trace-level identifier the function resolves it to the first
            concrete node before returning details.

    Returns:
        dict: A ``WebResponse``-compatible dictionary containing the node
        payload enriched with ``pre_id`` and ``next_id`` navigation helpers.
    """
    db_factory = DBFactory()
    if Config.get_es_config():
        jes_config = Config.get_es_config()
        hosts = jes_config["hosts"]
        user = jes_config["user"]
        password = jes_config["password"]
        es_client = db_factory.get_instance(JesEs, hosts, user, password)
    else:
        es_client = db_factory.get_instance(LocalEs)
    es_response = await es_client.search(
        Config.get_app_name() + "_node", {"query": {"term": {"_id": item_id}}}
    )
    try:
        datas = es_response["hits"]["hits"]
        if datas:
            node_data = datas[0]["_source"]
            trace_id = node_data["trace_id"]
        else:
            # puting item_id as trace_id
            trace_id = item_id

        """Get trace_id from trace table (abandoned)"""
        """If error, get trace_id from node table."""
        es_response = await es_client.search(
            Config.get_app_name() + "_node",
            {
                "query": {"term": {"trace_id": trace_id}},  # all of the nodes
                "size": 10000,
                "sort": [{"create_time": {"order": "asc"}}],
            },
        )
        node_ids = []
        for data in es_response["hits"]["hits"]:
            node_ids.append(data["_source"]["node_id"])

        if len(node_ids) == 0:
            return WebResponse(code=400, message="illegal node_id").to_dict()

        if trace_id == item_id:
            # puting item_id from trace_id，get node_id data for another time
            item_id = node_ids[0]
            es_response = await es_client.search(
                Config.get_app_name() + "_node", {"query": {"term": {"_id": item_id}}}
            )
            datas = es_response["hits"]["hits"]
            node_data = datas[0]["_source"]

        for i, node_id in enumerate(node_ids):
            if item_id == node_id:
                node_data["pre_id"] = node_ids[i - 1] if i >= 1 else ""
                node_data["next_id"] = node_ids[i + 1] if i <= len(node_ids) - 2 else ""

                if "input" in node_data:
                    node_data["input"] = json.loads(node_data["input"])

                if "prompt" in node_data["input"]["class_attr"]:
                    del node_data["input"]["class_attr"]["prompt"]
                env_value_to_key = {v: k for k, v in os.environ.items()}

                # Generate the maximum and minimum values for the data range
                node_data["data_range_map"] = dict()
                for tree in [
                    node_data["input"]["class_attr"],
                    node_data["input"]["class_attr"].get("llm_params", dict()),
                    node_data["input"]["arguments"],
                ]:
                    for k, v in tree.items():
                        if v and isinstance(v, str) and v in env_value_to_key:
                            tree[k] = f"${{{env_value_to_key[v]}}}"
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            if v <= 1:
                                max_value = 1
                            else:
                                max_value = v * 10
                            node_data["data_range_map"][k] = {
                                "min": 0,
                                "max": max_value,
                            }
                return WebResponse(data=node_data).to_dict()

    except Exception:
        error_msg = traceback.format_exc()
        logger.error(error_msg)
        return WebResponse(code=500, message="遇到问题").to_dict()


# Define the data model for the LLM call request
@router.get("/view")
async def get_task_info(item_id: str):
    db_factory = DBFactory()
    if Config.get_es_config():
        jes_config = Config.get_es_config()
        hosts = jes_config["hosts"]
        user = jes_config["user"]
        password = jes_config["password"]
        es_client = db_factory.get_instance(JesEs, hosts, user, password)
    else:
        es_client = db_factory.get_instance(LocalEs)

    # es_client.exists(Config.get_app_name() + "_node", doc_id=item_id)

    # If item_id is node_id
    es_response = await es_client.search(
        Config.get_app_name() + "_node", {"query": {"term": {"_id": item_id}}}
    )
    datas = es_response["hits"]["hits"]
    if datas:
        node_data = datas[0]["_source"]
        trace_id = node_data["trace_id"]
    else:
        # Input item_id as trace_id
        trace_id = item_id

    es_response = await es_client.search(
        Config.get_app_name() + "_node",
        {
            "query": {"term": {"trace_id": trace_id}},
            "size": 10000,
            "sort": [{"create_time": {"order": "asc"}}],
        },
    )
    nodes = []
    for data in es_response["hits"]["hits"]:
        data["_source"]["call_stack"] = data["_source"]["call_stack"]
        data["_source"]["node_id_stack"] = data["_source"]["node_id_stack"]
        data["_source"]["pre_node_ids"] = data["_source"]["pre_node_ids"]
        if (
            len(data["_source"]["pre_node_ids"]) == 1
            and data["_source"]["pre_node_ids"][0] == ""
        ):
            data["_source"]["pre_node_ids"] = []
        nodes.append(data["_source"])
    for index, node in enumerate(nodes):
        node["index"] = index
    add_post_and_child_node_ids(nodes)
    task_data = {"nodes": nodes, "trace_id": trace_id}
    return WebResponse(data=task_data).to_dict()


class Item(BaseModel):
    class_attr: dict
    arguments: dict


@router.post("/call")
async def call(item: Item):
    """Invoke an **OxyGent** agent according to the *Item* request.

    The endpoint supports ad-hoc overrides for both class constructor arguments
    (``class_attr`` field) and runtime ``arguments``.

    Example::

        POST /call
        {
            "class_attr": {"class_name": "api_llm", "max_tokens": 2048},
            "arguments": {"temperature": 0.7, "stream": False}
        }

    Args:
        item: The validated request payload.

    Returns:
        dict: ``WebResponse`` wrapper containing the model output.
    """
    try:
        # Preprocess environment variable substitutions
        pattern = r"^\$\{([a-zA-Z_][a-zA-Z0-9_]*)\}$"
        for tree in [
            item.class_attr,
            item.class_attr.get("llm_params", dict()),
            item.arguments,
        ]:
            for k, v in tree.items():
                if not isinstance(v, str):
                    continue
                match = re.match(pattern, v.strip())
                if match:
                    tree[k] = os.getenv(match.group(1), v)

        # Validate required field exists
        if "class_name" not in item.class_attr:
            return WebResponse(
                code=400, message="Missing required field: class_name"
            ).to_dict()

        # Set required name field
        item.class_attr["name"] = item.class_attr["class_name"].lower()

        # Type conversion for LLM parameters
        llm_params_type_dict = {
            "temperature": float,
            "max_tokens": int,
            "top_p": float,
        }
        for k, v in item.class_attr.get("llm_params", dict()).items():
            if k in llm_params_type_dict:
                try:
                    item.class_attr["llm_params"][k] = llm_params_type_dict[k](v)
                except (ValueError, TypeError) as e:
                    return WebResponse(
                        code=400, message=f"Invalid parameter {k}: {str(e)}"
                    ).to_dict()

        # Create Oxy instance with security checks and execute
        oxy = OxyFactory.create_oxy(item.class_attr["class_name"], **item.class_attr)
        oxy_response = await oxy.execute(OxyRequest(arguments=item.arguments))
        return WebResponse(data={"output": oxy_response.output}).to_dict()
    except SecurityError as e:
        logger.warning(
            f"Security check failed: {str(e)}",
            extra={"class_name": item.class_attr.get("class_name", "unknown")},
        )
        return WebResponse(code=403, message=f"Security error: {str(e)}").to_dict()
    except Exception:
        error_msg = traceback.format_exc()
        logger.error(f"Error in /call endpoint: {error_msg}")
        return WebResponse(code=500, message="Internal server error").to_dict()


class Script(BaseModel):
    """Schema for serialized *calling scripts* stored on disk.

    Attributes:
        name: Human-friendly script label displayed in the UI.
        contents: Arbitrary list structure that is later posted to ``/call``.
    """

    name: str
    contents: list


# ---------------------------------------------------------------------------
# Local *script* storage helpers
# ---------------------------------------------------------------------------


@router.get("/list_script")
def list_script():
    script_save_dir = os.path.join(Config.get_cache_save_dir(), "script")
    os.makedirs(script_save_dir, exist_ok=True)
    files = os.listdir(script_save_dir)
    if files:
        return WebResponse(
            data={
                "scripts": [
                    os.path.splitext(file)[0]
                    for file in files
                    if file.endswith(".json")
                ]
            }
        ).to_dict()
    else:
        return WebResponse(data={"scripts": []}).to_dict()


@router.post("/save_script")
def save_script(script: Script):
    """Persist a script definition to ``$CACHE_DIR/script``.

    Args:
        script: The script metadata and payload to store.

    Returns:
        dict: ``WebResponse`` with the generated ``script_id`` timestamp.
    """
    script_save_dir = os.path.join(Config.get_cache_save_dir(), "script")
    with open(os.path.join(script_save_dir, script.name + ".json"), "w") as f:
        f.write(json.dumps(script.contents, ensure_ascii=False))
    return WebResponse(data={"script_id": script.name + ".json"}).to_dict()


@router.get("/load_script")
def load_script(item_id: str):
    """Load a previously saved script.

    Args:
        script_id: Timestamp‑based identifier returned by :func:`save_script`.

    Returns:
        dict: ``WebResponse`` containing the original ``contents`` array or an
        error message when the file is missing.
    """
@router.get("/load_script")
def load_script(item_id: str):
    """Load a previously saved script.

    Args:
        script_id: Timestamp‑based identifier returned by :func:`save_script`.

    Returns:
        dict: ``WebResponse`` containing the original ``contents`` array or an
        error message when the file is missing.
    """
    script_save_dir = os.path.join(Config.get_cache_save_dir(), "script")

    json_path = os.path.join(script_save_dir, item_id + ".json")
    if not os.path.exists(json_path):
        return WebResponse(code=500, message="File not exist").to_dict()
    with open(json_path, "r") as f:
        return WebResponse(data={"contents": json.loads(f.read())}).to_dict()


# =============================================================================
# Prompt Management API Routes
# =============================================================================

# Prompt management request/response models
class PromptCreateRequest(BaseModel):
    prompt_key: str
    prompt_content: str
    description: str = ""
    category: str = "custom"
    agent_type: str = ""
    is_active: bool = True
    tags: List[str] = []
    created_by: str = "user"


class PromptUpdateRequest(BaseModel):
    prompt_content: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    agent_type: Optional[str] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None


class PromptResponse(BaseModel):
    id: str
    prompt_key: str
    prompt_content: str
    description: str
    category: str
    agent_type: str
    version: int
    created_at: str
    updated_at: str
    created_by: str
    tags: List[str]


class PromptApiResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None


@router.get("/api/prompts/", response_model=PromptApiResponse)
async def list_prompts(
    category: Optional[str] = Query(None, description="Category filter"),
    agent_type: Optional[str] = Query(None, description="Agent type filter"),
    is_active: Optional[bool] = Query(None, description="Active status filter"),
    tags: Optional[str] = Query(None, description="Tags filter, comma separated")
):
    """List prompts"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()
        tag_list = tags.split(",") if tags else None

        prompts = await manager.list_prompts(
            category=category,
            agent_type=agent_type,
            is_active=is_active,
            tags=tag_list
        )

        return PromptApiResponse(
            success=True,
            message="Successfully retrieved prompt list",
            data=prompts
        )
    except Exception as e:
        logger.error(f"Failed to list prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/prompts/{prompt_key}", response_model=PromptApiResponse)
async def get_prompt(prompt_key: str):
    """Get single prompt"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()
        # Use cache to get latest data (cache is updated immediately on save)
        prompt = await manager.get_prompt(prompt_key, use_cache=True)

        if not prompt:
            raise HTTPException(status_code=404, detail="Prompt not found")

        prompt["id"] = prompt_key
        return PromptApiResponse(
            success=True,
            message="Successfully retrieved prompt",
            data=prompt
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/prompts/", response_model=PromptApiResponse)
async def create_prompt(request: PromptCreateRequest):
    """Create prompt"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()

        # Check if already exists (use cache for consistency)
        existing = await manager.get_prompt(request.prompt_key, use_cache=True)
        if existing:
            raise HTTPException(status_code=400, detail="Prompt already exists")

        success = await manager.save_prompt(
            prompt_key=request.prompt_key,
            prompt_content=request.prompt_content,
            description=request.description,
            category=request.category,
            agent_type=request.agent_type,
            is_active=request.is_active,
            tags=request.tags,
            created_by=request.created_by
        )

        if not success:
            raise HTTPException(status_code=500, detail="Failed to create prompt")

        return PromptApiResponse(
            success=True,
            message="Successfully created prompt",
            data={"prompt_key": request.prompt_key}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create prompt: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/prompts/{prompt_key}", response_model=PromptApiResponse)
async def update_prompt(prompt_key: str, request: PromptUpdateRequest):
    """Update prompt"""
    try:
        from .live_prompt import get_prompt_manager, hot_reload_prompt
        manager = await get_prompt_manager()
        
        # Get existing prompt (use cache for cache-first strategy)
        existing = await manager.get_prompt(prompt_key, use_cache=True)
        if not existing:
            raise HTTPException(status_code=404, detail="Prompt not found")

        # Update fields
        update_data = {}
        if request.prompt_content is not None:
            update_data["prompt_content"] = request.prompt_content
        else:
            update_data["prompt_content"] = existing["prompt_content"]

        if request.description is not None:
            update_data["description"] = request.description
        else:
            update_data["description"] = existing.get("description", "")

        if request.category is not None:
            update_data["category"] = request.category
        else:
            update_data["category"] = existing.get("category", "custom")

        if request.agent_type is not None:
            update_data["agent_type"] = request.agent_type
        else:
            update_data["agent_type"] = existing.get("agent_type", "")

        if request.tags is not None:
            update_data["tags"] = request.tags
        else:
            update_data["tags"] = existing.get("tags", [])

        success = await manager.save_prompt(
            prompt_key=prompt_key,
            **update_data,
            is_active=request.is_active if request.is_active is not None else existing.get("is_active", True),
            created_by=existing.get("created_by", "user")
        )

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update prompt")

        hot_reload_success = False
        if request.prompt_content is not None:
            hot_reload_success = await hot_reload_prompt(prompt_key)
        
        return PromptApiResponse(
            success=True,
            message="Successfully updated prompt" + (
                ", auto hot-reloaded to all related agents" if hot_reload_success else ""
            ),
            data={
                "prompt_key": prompt_key,
                "hot_reload_success": hot_reload_success,
                "auto_updated": hot_reload_success
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/prompts/{prompt_key}", response_model=PromptApiResponse)
async def delete_prompt(prompt_key: str):
    """Delete prompt"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()
        success = await manager.delete_prompt(prompt_key)

        if not success:
            raise HTTPException(status_code=404, detail="Prompt not found")

        return PromptApiResponse(
            success=True,
            message="Successfully deleted prompt",
            data={"prompt_key": prompt_key}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/prompts/search/", response_model=PromptApiResponse)
async def search_prompts(
    keyword: str = Query(..., description="Search keyword"),
    category: Optional[str] = Query(None, description="Category filter")
):
    """Search prompts"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()
        results = await manager.search_prompts(keyword, category)

        return PromptApiResponse(
            success=True,
            message="Successfully searched prompts",
            data=results
        )
    except Exception as e:
        logger.error(f"Failed to search prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/prompts/hot-reload/{prompt_key}", response_model=PromptApiResponse)
async def hot_reload_prompt_by_key(prompt_key: str):
    """Hot reload specified prompt to all related agents"""
    try:
        from .live_prompt import hot_reload_prompt, dynamic_agent_manager

        # Execute hot reload
        success = await hot_reload_prompt(prompt_key)

        if not success:
            return PromptApiResponse(
                success=False,
                message=f"No agents found using prompt {prompt_key} or update failed",
                data={"prompt_key": prompt_key, "updated_agents": []}
            )

        # Get list of updated agents
        agent_mapping = dynamic_agent_manager.get_agent_prompt_mapping()
        updated_agents = [
            agent_name for agent_name, key in agent_mapping.items()
            if key == prompt_key
        ]

        return PromptApiResponse(
            success=True,
            message=f"Successfully hot reloaded prompt {prompt_key}",
            data={
                "prompt_key": prompt_key,
                "updated_agents": updated_agents,
                "reload_time": datetime.now().isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Failed to hot reload prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/prompts/hot-reload/agent/{agent_name}", response_model=PromptApiResponse)
async def hot_reload_agent_prompt(agent_name: str):
    """Hot reload prompt for specified agent"""
    try:
        from .live_prompt import hot_reload_agent, dynamic_agent_manager

        success = await hot_reload_agent(agent_name)

        if not success:
            return PromptApiResponse(
                success=False,
                message=f"Agent {agent_name} not found or update failed",
                data={"agent_name": agent_name}
            )

        # Get agent's corresponding prompt key
        agent_mapping = dynamic_agent_manager.get_agent_prompt_mapping()
        prompt_key = agent_mapping.get(agent_name, "unknown")

        return PromptApiResponse(
            success=True,
            message=f"Successfully hot reloaded agent {agent_name}'s prompt",
            data={
                "agent_name": agent_name,
                "prompt_key": prompt_key,
                "reload_time": datetime.now().isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Failed to hot reload agent {agent_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/prompts/hot-reload/all", response_model=PromptApiResponse)
async def hot_reload_all_agent_prompts():
    """Hot reload all agent prompts"""
    try:
        from .live_prompt import hot_reload_all_prompts

        results = await hot_reload_all_prompts()

        return PromptApiResponse(
            success=bool(results),
            message="Successfully completed batch hot reload" if results else "No agents to reload",
            data={
                "reload_success": results,
                "reload_time": datetime.now().isoformat()
            }
        )
    except Exception as e:
        logger.error(f"Failed to hot reload all prompts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Prompt Version Management API Routes
# =============================================================================

@router.get("/api/prompts/{prompt_key}/history", response_model=PromptApiResponse)
async def get_prompt_history(prompt_key: str):
    """Get prompt version history"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()
        history = await manager.get_prompt_history(prompt_key)

        return PromptApiResponse(
            success=True,
            message="Successfully retrieved prompt history",
            data=history
        )
    except Exception as e:
        logger.error(f"Failed to get prompt history for {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/prompts/{prompt_key}/revert/{target_version}", response_model=PromptApiResponse)
async def revert_prompt_to_version(prompt_key: str, target_version: int):
    """Revert prompt to specific version"""
    try:
        from .live_prompt import get_prompt_manager, hot_reload_prompt
        manager = await get_prompt_manager()

        # Check if prompt exists (without cache to ensure fresh check)
        existing = await manager.get_prompt(prompt_key, use_cache=False)
        if not existing:
            raise HTTPException(status_code=404, detail="Prompt not found")

        # Revert to target version
        success = await manager.revert_to_version(prompt_key, target_version)

        if not success:
            raise HTTPException(status_code=400, detail=f"Failed to revert to version {target_version}")

        # Auto hot reload after revert
        hot_reload_success = await hot_reload_prompt(prompt_key)

        return PromptApiResponse(
            success=True,
            message=f"Successfully reverted {prompt_key} to version {target_version}",
            data={
                "prompt_key": prompt_key,
                "reverted_to_version": target_version,
                "hot_reload_success": hot_reload_success,
                "revert_time": datetime.now().isoformat()
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revert prompt {prompt_key} to version {target_version}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/prompts/{prompt_key}/version/{version}", response_model=PromptApiResponse)
async def get_prompt_version(prompt_key: str, version: int):
    """Get specific version of a prompt"""
    try:
        from .live_prompt import get_prompt_manager
        manager = await get_prompt_manager()

        # Get version history
        history = await manager.get_prompt_history(prompt_key)

        # Find the specific version
        target_version = None
        for hist in history:
            if hist.get("version") == version:
                target_version = hist
                break

        if not target_version:
            raise HTTPException(status_code=404, detail=f"Version {version} not found for prompt {prompt_key}")

        return PromptApiResponse(
            success=True,
            message=f"Successfully retrieved version {version} of prompt {prompt_key}",
            data=target_version
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get version {version} of prompt {prompt_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Agent Management API Routes
# =============================================================================

# Global MAS instance reference
_global_mas_instance = None

def set_global_mas_instance(mas_instance):
    """Set global MAS instance for API access"""
    global _global_mas_instance
    _global_mas_instance = mas_instance

@router.get("/get_agents")
async def get_agents():
    """Get agents information from MAS instance"""
    try:
        global _global_mas_instance
        if _global_mas_instance is None:
            return WebResponse(code=400, message="MAS instance not available").to_dict()

        # Extract agent information from MAS
        agents = []

        # Get agents from oxy_name_to_oxy registry
        for agent_name, oxy_instance in _global_mas_instance.oxy_name_to_oxy.items():
            if hasattr(oxy_instance, '__class__') and hasattr(oxy_instance, 'desc'):
                agent_info = {
                    "name": agent_name,
                    "desc": getattr(oxy_instance, 'desc', ''),
                    "type": "agent",
                    "class_name": oxy_instance.__class__.__name__,
                    "path": [agent_name]
                }
                agents.append(agent_info)

        return WebResponse(
            code=200,
            message="Successfully retrieved agents",
            data={"agents": agents}
        ).to_dict()

    except Exception as e:
        logger.error(f"Failed to get agents: {e}")
        return WebResponse(code=500, message=f"Failed to get agents: {str(e)}").to_dict()
