"""
Live Prompts - Real-time Agent Prompt Management
Provides get_live_prompts() function for agents to automatically load prompts from storage
"""

import logging
import asyncio
from .manager import get_dynamic_prompt

logger = logging.getLogger(__name__)

# Global cache for live prompts to handle async/sync context issues
_live_prompt_cache = {}


def get_live_prompts(prompt_key: str, default_prompt: str = None) -> str:
    """
    Get live prompt by prompt key with immediate storage resolution.

    Logic:
    1. First try to resolve from storage using prompt_key
    2. If not found and default_prompt is provided, use default_prompt
    3. If not found and default_prompt is None/empty, return ""

    Usage:
    oxy.ReActAgent(
        name="file_agent",
        desc="A tool that can operate the file system",
        tools=["file_tools"],
        prompt=get_live_prompts("file_agent_prompt", "Default system prompt")
    ),

    Returns prompt from storage, or default_prompt, or empty string.
    """
    try:
        # Check if in an async context
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No event loop running, create a new one
            pass

        if loop and loop.is_running():
            # in an async context, can't use asyncio.run()
            # Schedule the resolution for later and return default for now
            logger.debug(f"In async context, scheduling ES resolution for '{prompt_key}'")

            # Create a task to resolve the prompt asynchronously
            async def resolve_and_update():
                try:
                    result = await _resolve_prompt_from_es(prompt_key, default_prompt or "")
                    # Store in a global cache for future synchronous access
                    _live_prompt_cache[prompt_key] = result
                    logger.debug(f"Cached live prompt for '{prompt_key}': {len(result)} chars")
                except Exception as e:
                    logger.warning(f"Failed to resolve and cache prompt '{prompt_key}': {e}")

            # Schedule the task but don't wait for it
            asyncio.create_task(resolve_and_update())

            # Check if we have a cached version first
            if prompt_key in _live_prompt_cache:
                cached_prompt = _live_prompt_cache[prompt_key]
                if cached_prompt:
                    logger.debug(f"Using cached live prompt for '{prompt_key}': {len(cached_prompt)} chars")
                    return cached_prompt

            # Return default prompt for immediate use
            if default_prompt is not None and default_prompt.strip():
                logger.debug(f"Using default prompt for '{prompt_key}' (async context): {len(default_prompt)} chars")
                return default_prompt
            return ""
        else:
            # in sync context, can create new event loop
            try:
                result = asyncio.run(_resolve_prompt_from_es(prompt_key, default_prompt or ""))
                logger.debug(f"Resolved prompt for '{prompt_key}' from storage: {len(result)} chars")
                # Cache the result
                _live_prompt_cache[prompt_key] = result
                return result
            except Exception as e:
                logger.warning(f"Failed to resolve prompt from ES for '{prompt_key}': {e}")
                # Fall back to default_prompt
                if default_prompt is not None and default_prompt.strip():
                    logger.debug(f"Using default prompt for '{prompt_key}': {len(default_prompt)} chars")
                    return default_prompt
                return ""

    except Exception as e:
        logger.error(f"Error in get_hot_prompts for '{prompt_key}': {e}")
        # Fall back to default_prompt
        if default_prompt is not None and default_prompt.strip():
            return default_prompt
        return ""


async def _resolve_prompt_from_es(prompt_key: str, default_prompt: str = "") -> str:
    """
    Resolve prompt content from ES using the exact prompt_key

    Args:
        prompt_key: The exact prompt key to search for in ES
        default_prompt: Fallback prompt if not found in ES

    Returns:
        str: Prompt content from ES, or default_prompt, or empty string

    Logic:
    1. Try to get prompt from ES using the exact prompt_key
    2. If found and active, return the content
    3. If not found, return default_prompt
    4. If default_prompt is empty, return "" (system uses built-in defaults)
    """
    try:
        # Use the exact prompt key provided
        prompt_content = await get_dynamic_prompt(prompt_key, default_prompt)

        if prompt_content and prompt_content != default_prompt:
            logger.info(f"Loaded hot prompt from ES: {prompt_key}")
            return prompt_content

        # If no dynamic prompt found, use default or empty string
        if default_prompt and default_prompt.strip():
            logger.info(f"Using default prompt for {prompt_key}")
            return default_prompt
        else:
            logger.info(f"No prompt found for {prompt_key}, using system default")
            return ""

    except Exception as e:
        logger.error(f"Failed to resolve hot prompt for {prompt_key}: {e}")
        # Return default prompt or empty string on error
        return default_prompt if default_prompt else ""