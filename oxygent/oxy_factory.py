"""oxy_factory.py Factory for creating OxyGent operators.xs."""

from typing import Any


class SecurityError(Exception):
    """Raised when attempting to create a potentially unsafe Oxy component."""
    pass


class OxyFactory:
    # Dangerous classes that should not be created externally
    # These classes can execute system commands, make network requests, or access sensitive resources
    _DANGEROUS_CLASSES = {
        "ChatAgent",
        "ReActAgent",
        "WorkflowAgent",
        "HttpTool",
        "MCPTool",
        "StdioMCPClient",
        "SSEMCPClient",
        "FunctionTool",
        "Workflow",
    }

    # Initialize creators mapping at module load time
    _creators = {}

    @classmethod
    def _init_creators(cls):
        """Initialize the class creators mapping."""
        from .oxy import (
            ChatAgent,
            ReActAgent,
            WorkflowAgent,
            HttpTool,
            HttpLLM,
            OpenAILLM,
            MCPTool,
            StdioMCPClient,
            SSEMCPClient,
            FunctionTool,
            Workflow,
        )
        
        cls._creators.update({
            "ChatAgent": ChatAgent,
            "ReActAgent": ReActAgent,
            "WorkflowAgent": WorkflowAgent,
            "HttpTool": HttpTool,
            "HttpLLM": HttpLLM,
            "OpenAILLM": OpenAILLM,
            "MCPTool": MCPTool,
            "StdioMCPClient": StdioMCPClient,
            "SSEMCPClient": SSEMCPClient,
            "FunctionTool": FunctionTool,
            "Workflow": Workflow,
        })

    @staticmethod
    def create_oxy(operator_class_name: str, **kwargs) -> Any:
        """
        Create an Oxy component with basic security checks.
        
        This method provides a simple way to create Oxy components while
        preventing the creation of dangerous classes that could be used
        for RCE attacks.
        
        Args:
            operator_class_name: Class name to create
            **kwargs: Class constructor parameters
            
        Returns:
            Oxy component instance
            
        Raises:
            SecurityError: If attempting to create unsafe component
        """
        # Block dangerous classes that can be used for RCE attacks
        if operator_class_name in OxyFactory._DANGEROUS_CLASSES:
            raise SecurityError(f"Class {operator_class_name} is not allowed for external calls")
        
        # Verify class exists
        if operator_class_name not in OxyFactory._creators:
            raise SecurityError(f"Unknown class: {operator_class_name}")
        
        return OxyFactory._creators[operator_class_name](**kwargs)


# Initialize creators when module is loaded
OxyFactory._init_creators()
