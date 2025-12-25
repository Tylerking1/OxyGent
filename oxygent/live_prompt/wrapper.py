"""
Live Prompt Agent Wrapper - Simplified
Provides hot-reload functionality for agent prompts with real-time updates
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class DynamicAgentManager:
    """Simplified dynamic agent manager"""

    def __init__(self):
        self.agent_prompt_mapping: Dict[str, str] = {}
        self.mas_instance = None

    def register_agents_from_mas(self, mas_instance):
        """
        Auto-register agents that use live prompts from MAS instance

        Args:
            mas_instance: MAS instance
        """
        try:
            self.mas_instance = mas_instance
            actual_agents = list(mas_instance.oxy_name_to_oxy.keys())
            logger.info(f"Found {len(actual_agents)} agents in MAS: {actual_agents}")

            live_prompt_agents = []

            # Only register agents that use get_live_prompts
            for agent_name in actual_agents:
                agent_instance = mas_instance.oxy_name_to_oxy[agent_name]

                # Check if this agent uses live prompts by examining its prompt
                if self._agent_uses_live_prompts(agent_instance):
                    prompt_key = f"{agent_name}_prompt"
                    self.agent_prompt_mapping[agent_name] = prompt_key
                    live_prompt_agents.append(agent_name)
                    logger.info(f"Registered live prompt agent: {agent_name}")
                else:
                    logger.debug(f"Skipping agent without live prompts: {agent_name}")

            logger.info(f"Live prompt registration completed: {len(live_prompt_agents)} agents registered")
            logger.info(f"Live prompt agents: {live_prompt_agents}")
            return len(live_prompt_agents) > 0

        except Exception as e:
            logger.error(f"Live prompt registration failed: {e}")
            return False

    def _agent_uses_live_prompts(self, agent_instance) -> bool:
        """
        Check if an agent uses live prompts by examining its prompt attribute

        Args:
            agent_instance: Agent instance to check

        Returns:
            bool: True if agent uses live prompts, False otherwise
        """
        try:
            # Check if agent has a prompt attribute
            if not hasattr(agent_instance, 'prompt'):
                return False
            return True

        except Exception as e:
            logger.warning(f"Error checking if agent uses live prompts: {e}")
            return False

    async def update_agent_prompt(self, agent_name: str) -> bool:
        """
        Update prompt for specified agent

        Args:
            agent_name: Agent name

        Returns:
            bool: Whether update was successful
        """
        if not self.mas_instance or agent_name not in self.agent_prompt_mapping:
            logger.warning(f"Agent not found: {agent_name}")
            return False

        try:
            from .manager import get_prompt_manager

            prompt_key = self.agent_prompt_mapping[agent_name]
            agent_instance = self.mas_instance.oxy_name_to_oxy[agent_name]

            # Get manager (cache may already have latest data from save_prompt)
            manager = await get_prompt_manager()
            logger.debug(f"Hot reload for {agent_name} using prompt_key: {prompt_key}")

            # Use agent's reload_prompt method if available
            if hasattr(agent_instance, 'reload_prompt'):
                success = await agent_instance.reload_prompt()
                if success:
                    logger.info(f"Hot-reloaded prompt for: {agent_name}")
                return success
            # Fallback to old approach for backward compatibility
            elif hasattr(agent_instance, 'prompt'):
                from .manager import resolve_prompt_from_es
                
                # Get original prompt as fallback
                original_prompt = getattr(agent_instance, 'prompt', '')
                
                # Get latest prompt from ES
                new_prompt = await resolve_prompt_from_es(prompt_key, original_prompt)
                
                # Update agent prompt
                agent_instance.prompt = new_prompt

                # Re-set description for LLM if method exists
                if hasattr(agent_instance, '_set_desc_for_llm'):
                    agent_instance._set_desc_for_llm()

                logger.info(f"Updated prompt for: {agent_name}")
                return True
            else:
                logger.warning(f"Agent has no prompt attribute or reload_prompt method: {agent_name}")
                return False

        except ConnectionError as e:
            logger.error(f"Connection error updating prompt for {agent_name}: {e}")
            logger.info(f"Will retry on next hot reload request")
            return False
        except Exception as e:
            logger.error(f"Failed to update prompt for {agent_name}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False

    async def update_all_prompts(self) -> Dict[str, bool]:
        """
        Update prompts for all agents

        Returns:
            Dict[str, bool]: Update results for each agent
        """
        results = {}
        for agent_name in self.agent_prompt_mapping.keys():
            results[agent_name] = await self.update_agent_prompt(agent_name)

        success_count = sum(1 for success in results.values() if success)
        total_count = len(results)
        logger.info(f"Batch prompt update completed: {success_count}/{total_count} successful")

        return results

    async def update_prompt_by_key(self, prompt_key: str) -> Dict[str, bool]:
        """
        Update all agents using specified prompt key

        Args:
            prompt_key: Prompt key name

        Returns:
            Dict[str, bool]: Update results for each agent
        """
        results = {}
        for agent_name, key in self.agent_prompt_mapping.items():
            if key == prompt_key:
                results[agent_name] = await self.update_agent_prompt(agent_name)

        if results:
            success_count = sum(1 for success in results.values() if success)
            total_count = len(results)
            logger.info(f"Prompt key update completed ({prompt_key}): {success_count}/{total_count} successful")
        else:
            logger.warning(f"No agents found using prompt key: {prompt_key}")

        return results

    def get_agent_prompt_mapping(self) -> Dict[str, str]:
        """Get agent to prompt mapping"""
        return self.agent_prompt_mapping.copy()


# Global dynamic agent manager instance
dynamic_agent_manager = DynamicAgentManager()


async def setup_dynamic_agents(mas_instance):
    """
    Setup dynamic prompt functionality for agents in MAS instance

    Args:
        mas_instance: MAS instance
    """
    logger.info("Setting up dynamic agents...")

    # Use auto-registration
    success = dynamic_agent_manager.register_agents_from_mas(mas_instance)

    if success:
        registered_count = len(dynamic_agent_manager.agent_prompt_mapping)
        logger.info(f"Dynamic agent manager setup completed: {registered_count} agents registered")

        # Print registered agents
        agent_mapping = dynamic_agent_manager.get_agent_prompt_mapping()
        for agent_name, prompt_key in agent_mapping.items():
            logger.info(f"{agent_name} ↔ {prompt_key}")

        # Auto-save existing agent prompts to database
        await auto_save_agent_prompts_to_database(mas_instance)
    else:
        logger.info("Dynamic agent manager setup failed")


async def auto_save_agent_prompts_to_database(mas_instance):
    """
    Auto-save existing agent prompts to database for first-time setup

    Args:
        mas_instance: MAS instance
    """
    try:
        from .manager import get_prompt_manager

        # Use global singleton prompt manager (CRITICAL: ensures cache consistency)
        manager = await get_prompt_manager()

        # Get existing prompts from database to avoid duplicates
        existing_prompts = await manager.list_prompts()
        existing_keys = {prompt.get('prompt_key') for prompt in existing_prompts}

        saved_count = 0
        skipped_count = 0

        # Save prompts for registered live prompt agents only
        for agent_name in dynamic_agent_manager.agent_prompt_mapping.keys():
            agent_instance = mas_instance.oxy_name_to_oxy[agent_name]
            prompt_key = f"{agent_name}_prompt"

            # Skip if prompt already exists in database
            if prompt_key in existing_keys:
                skipped_count += 1
                continue

            # Get agent's current prompt
            prompt_content = getattr(agent_instance, 'prompt', '')
            if not prompt_content:
                # Try to get a default prompt or description
                prompt_content = getattr(agent_instance, 'description', f'Default prompt for {agent_name}')

            # Determine agent type
            agent_type = type(agent_instance).__name__

            # Save prompt to database
            try:
                success = await manager.save_prompt(
                    prompt_key=prompt_key,
                    prompt_content=prompt_content,
                    agent_type=agent_type,
                    is_active=True,
                    version=1,
                    description=f"Auto-generated prompt for {agent_name}",
                    category="agent",
                    created_by="system_auto_setup"
                )

                if success:
                    saved_count += 1
                    logger.info(f"Auto-saved prompt for {agent_name}")
                else:
                    logger.warning(f"Failed to save prompt for {agent_name}")

            except Exception as e:
                logger.error(f"Error saving prompt for {agent_name}: {e}")

        if saved_count > 0:
            logger.info(f"Auto-saved {saved_count} agent prompts to database")
        if skipped_count > 0:
            logger.info(f"⏭Skipped {skipped_count} existing prompts")

    except Exception as e:
        logger.error(f"Failed to auto-save agent prompts: {e}")
        import traceback
        traceback.print_exc()


# Convenient hot-reload functions
async def hot_reload_prompt(prompt_key: str) -> bool:
    """
    Hot reload specified prompt

    Args:
        prompt_key: Prompt key name

    Returns:
        bool: Whether any agent was successfully updated
        
    Note:
        No cache clearing needed - save_prompt already updated cache.
        Agent reload_prompt will fetch latest data from cache.
    """
    results = await dynamic_agent_manager.update_prompt_by_key(prompt_key)
    return any(results.values()) if results else False


async def hot_reload_all_prompts() -> bool:
    """
    Hot reload all prompts

    Returns:
        bool: Whether at least one agent was successfully updated
        
    Note:
        No cache clearing needed - save_prompt already updated cache.
        Agent reload_prompt will fetch latest data from cache.
    """
    results = await dynamic_agent_manager.update_all_prompts()
    return any(results.values()) if results else False


async def hot_reload_agent(agent_name: str) -> bool:
    """
    Hot reload prompt for specified agent

    Args:
        agent_name: Agent name

    Returns:
        bool: Whether update was successful
    """
    return await dynamic_agent_manager.update_agent_prompt(agent_name)