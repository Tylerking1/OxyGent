"""A stateful code interpreter tool that can execute Python code.

This module provides tools to execute Python code in isolated Jupyter kernels
with stateful sessions. It's particularly useful for complex computations,
data analysis, and multi-step programming tasks.

Key Features:
- Stateful execution: Variables and imports persist across multiple calls with the same session_id
- Isolated environment: Each session runs in its own Jupyter kernel for security
- Rich output handling: Captures stdout, expression results, and error messages
- Resource management: Explicit session lifecycle with start/stop controls

Setup:
To use this tool, ensure Jupyter client and ipykernel are installed:

    pip install jupyter_client ipykernel

If needed, register the kernel:

    python -m ipykernel install --user

Example Usage Scenarios:

1. Data Analysis:
   execute_code(
       session_id="data_analysis",
       code='''
import pandas as pd
import numpy as np
data = pd.DataFrame({'x': [1, 2, 3, 4, 5], 'y': [2, 4, 6, 8, 10]})
print("Correlation:", data.corr().iloc[0, 1])
print("Mean of x:", data['x'].mean())
'''
   )

2. Multi-step Mathematical Computation:
   # Step 1: Define complex function
   execute_code(
       session_id="math_calc",
       code='''
import math
def complex_calculation(x, y):
    return math.sin(x) * math.cos(y) + math.sqrt(x**2 + y**2)
'''
   )
   
   # Step 2: Use the function
   execute_code(
       session_id="math_calc",
       code='''
result = complex_calculation(3.14, 2.71)
print(f"Result: {result}")
'''
   )

3. Machine Learning Prototype:
   execute_code(
       session_id="ml_prototype",
       code='''
from sklearn.linear_model import LinearRegression
import numpy as np
X = np.array([[1], [2], [3], [4], [5]])
y = np.array([2, 4, 6, 8, 10])
model = LinearRegression().fit(X, y)
prediction = model.predict([[6]])
print(f"Prediction for x=6: {prediction[0]}")
'''
   )

4. Simple Calculations:
   execute_code(
       session_id="simple_calc",
       code="print('Hello, OxyGent!'); result = 10 + 20; print(f'Sum: {result}')"
   )
   
   # Clean up when done
   stop_session(session_id="simple_calc")

5. Error Handling:
   execute_code(
       session_id="error_test",
       code="undefined_variable + 1"
   )
   # Returns: "NameError: name 'undefined_variable' is not defined"

6. Session State Persistence:
   # First call - initialize data
   execute_code(
       session_id="persistent_session",
       code="data = [1, 2, 3, 4, 5]; print('Data initialized')"
   )
   
   # Second call - use data from first call
   execute_code(
       session_id="persistent_session",
       code="print('Length:', len(data)); print('Sum:', sum(data))"
   )
   
   # Clean up
   stop_session(session_id="persistent_session")
"""

import asyncio
import logging
import threading
import time
from queue import Empty

from jupyter_client.manager import KernelManager
from pydantic import Field

from oxygent.oxy import FunctionHub

logger = logging.getLogger(__name__)

code_interpreter_tools = FunctionHub(name="code_interpreter_tools")


class CodeInterpreter:
    """Synchronous class to manage Jupyter kernels and execute code.

    This class handles the lifecycle of Jupyter kernels and provides
    thread-safe code execution capabilities. Each session gets its own
    isolated kernel environment.
    """

    def __init__(self):
        """Initialize the CodeInterpreter with empty sessions dictionary."""
        self.sessions: dict[str, dict] = {}
        self._global_lock = threading.RLock()

    def start_kernel(self, session_id: str):
        """Start a new Jupyter kernel for the given session ID.
        
        If a kernel already exists for this session_id, returns the existing one.
        
        Args:
            session_id (str): Unique identifier for the session
            
        Returns:
            dict: Session dictionary containing kernel manager, client, and lock
            
        Raises:
            RuntimeError: If kernel fails to start
        """
        with self._global_lock:
            session = self.sessions.get(session_id)
            if session:
                return session
            km = KernelManager()
            try:
                km.start_kernel()
                client = km.client()
                client.start_channels()
                # Wait for the kernel to be ready to avoid first-call race
                try:
                    # Some client impls provide wait_for_ready
                    wait_for_ready = getattr(client, "wait_for_ready", None)
                    if callable(wait_for_ready):
                        wait_for_ready(timeout=30)
                    else:
                        # Fallback: small grace period to allow kernel to initialize
                        time.sleep(0.5)
                except Exception as e:
                    logger.debug("Kernel wait_for_ready encountered an issue: %s", e)
            except Exception as e:
                logger.error("Failed to start kernel for session %s: %s", session_id, e)
                raise RuntimeError(f"Error starting Jupyter kernel: {e}") from e
            session = {
                "kernel_manager": km,
                "client": client,
                "lock": threading.RLock(),
            }
            self.sessions[session_id] = session
            return session

    def stop_kernel(self, session_id: str):
        """Stop and cleanup the Jupyter kernel for the given session ID.
        
        Args:
            session_id (str): Unique identifier for the session to stop
        """
        with self._global_lock:
            if session_id in self.sessions:
                session = self.sessions[session_id]
                try:
                    session["client"].stop_channels()
                except Exception as e:
                    logger.debug("stop_channels error for %s: %s", session_id, e)
                try:
                    session["kernel_manager"].shutdown_kernel()
                except Exception as e:
                    logger.debug("shutdown_kernel error for %s: %s", session_id, e)
                del self.sessions[session_id]

    def _collect_outputs(self, client, msg_id: str, total_timeout: float = 30.0) -> str:
        """Collect all output messages from the kernel execution.
        
        Args:
            client: Jupyter client instance
            msg_id (str): Message ID to track
            total_timeout (float): Maximum time to wait for output
            
        Returns:
            str: Combined output from all messages
        """
        outputs: list[str] = []
        deadline = time.time() + total_timeout
        saw_idle = False
        while time.time() < deadline:
            try:
                msg = client.get_iopub_msg(timeout=0.5)
            except Empty:
                continue
            except Exception as e:
                logger.debug("get_iopub_msg error: %s", e)
                continue

            msg_type = msg.get("header", {}).get("msg_type")
            parent_id = msg.get("parent_header", {}).get("msg_id")

            # 'status' messages may not always carry the same parent id
            if msg_type != "status" and parent_id != msg_id:
                continue

            if msg_type == "status":
                state = msg.get("content", {}).get("execution_state")
                if state == "idle":
                    saw_idle = True
                    break
                continue

            if msg_type == "stream":
                outputs.append(msg.get("content", {}).get("text", ""))
            elif msg_type in ("execute_result", "display_data"):
                data = msg.get("content", {}).get("data", {})
                text = data.get("text/plain")
                if text:
                    outputs.append(text)
            elif msg_type == "error":
                ename = msg.get("content", {}).get("ename", "")
                evalue = msg.get("content", {}).get("evalue", "")
                outputs.append(f"{ename}: {evalue}")

        # Best-effort: ensure we have received execute_reply for our message
        try:
            while time.time() < deadline:
                reply = client.get_shell_msg(timeout=0.1)
                if reply.get("parent_header", {}).get("msg_id") == msg_id:
                    break
        except Exception:
            pass

        return "\n".join([o for o in outputs if o]).strip()

    def execute_code(self, session_id: str, code: str) -> str:
        """Execute Python code in the specified session's kernel.
        
        Args:
            session_id (str): Session identifier
            code (str): Python code to execute
            
        Returns:
            str: Output from code execution
            
        Raises:
            RuntimeError: If kernel fails to start or execute code
        """
        session = self.start_kernel(session_id)
        client = session["client"]
        # Serialize execution per session to prevent concurrent reads on client queues
        with session["lock"]:
            msg_id = client.execute(code)
            return self._collect_outputs(client, msg_id)


code_interpreter_instance = CodeInterpreter()


@code_interpreter_tools.tool(
    description="Executes Python code in a stateful session. Use the same session_id to maintain state across multiple calls."
)
async def execute_code(
    session_id: str = Field(
        description="The identifier for the execution session. All code with the same session_id will run in the same environment."
    ),
    code: str = Field(description="The Python code to execute."),
) -> str:
    """Execute Python code in a stateful Jupyter kernel session.
    
    This tool runs Python code in an isolated Jupyter kernel, allowing for
    stateful execution across multiple calls with the same session_id.
    
    Args:
        session_id (str): Identifier for the execution session. All code with
            the same session_id shares the same kernel environment.
        code (str): Python code to execute. Can be multiple lines.
            
    Returns:
        str: The output from the code execution, including printed text,
            expression results, and error messages.
            
    Example:
        >>> execute_code(session_id="calc", code="x = 5; y = 10; print(x + y)")
        '15'
        
        >>> execute_code(session_id="calc", code="print(x * y)")  # Uses variables from previous call
        '50'
        
    Note:
        - Variables and imports persist within the same session
        - Each session runs in an isolated Jupyter kernel
        - Remember to call stop_session when finished to free resources
        - Errors are returned as formatted strings, not raised as exceptions
    """
    loop = asyncio.get_running_loop()
    if not session_id or not isinstance(session_id, str):
        return "Error: 'session_id' must be a non-empty string"
    if not code or not isinstance(code, str):
        return "Error: 'code' must be a non-empty string"
    try:
        result = await loop.run_in_executor(
            None,
            code_interpreter_instance.execute_code,
            session_id,
            code,
        )
        return result
    except Exception as e:
        logger.warning("Code execution failed for session %s: %s", session_id, e)
        return f"Error: {e}"


@code_interpreter_tools.tool(description="Stops a session and cleans up its resources.")
async def stop_session(
    session_id: str = Field(
        description="The identifier for the execution session to stop."
    ),
) -> str:
    """Stop a session and clean up its resources.
    
    This tool terminates the Jupyter kernel associated with the session
    and frees up all resources.
    
    Args:
        session_id (str): Identifier for the session to stop.
        
    Returns:
        str: Confirmation message that the session has been stopped.
        
    Example:
        >>> stop_session(session_id="calc")
        'Session calc stopped.'
        
    Note:
        - Always call this when finished with a session to free resources
        - Once stopped, the session cannot be resumed
        - Errors are returned as formatted strings, not raised as exceptions
    """
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, code_interpreter_instance.stop_kernel, session_id)
        return f"Session {session_id} stopped."
    except Exception as e:
        logger.warning("Failed to stop session %s: %s", session_id, e)
        return f"Error: {e}"