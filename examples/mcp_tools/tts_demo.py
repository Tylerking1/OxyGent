"""
TTS MCP Service Test Demo

This demo shows how to use the optimized TTS MCP service with OxyGent framework.
"""

import os
import sys
import asyncio
from oxygent import MAS, Config, oxy

# Configure the default LLM
Config.set_agent_llm_model("default_llm")

# Get the absolute path to the project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TTS_TOOLS_PATH = os.path.join(PROJECT_ROOT, "mcp_servers", "tts_tools.py")

# Define the oxy space with optimized TTS tools
oxy_space = [
    # LLM configuration
    oxy.HttpLLM(
        name="default_llm",
        api_key=os.getenv("DEFAULT_LLM_API_KEY"),
        base_url=os.getenv("DEFAULT_LLM_BASE_URL"),
        model_name=os.getenv("DEFAULT_LLM_MODEL_NAME"),
    ),

    # Optimized TTS MCP Client
    oxy.StdioMCPClient(
        name="tts_tools",
        params={
            "command": sys.executable,  # 使用当前 Python 解释器
            "args": [TTS_TOOLS_PATH],
        },
    ),

    # TTS Agent that can handle text-to-speech requests
    oxy.ReActAgent(
        name="tts_agent",
        desc="An advanced text-to-speech agent using Edge TTS with automatic caching and playback",
        tools=["tts_tools"],
        system_prompt="""You are an advanced Text-to-Speech assistant powered by Microsoft Edge TTS. You can:

🗣️ **Speech Playback:**
- text_to_speech(text, voice) - Play text as speech with automatic caching
  * text: The text to convert and play
  * voice: Voice ID (default: zh-CN-XiaoxiaoNeural)
  * This function ALWAYS plays the audio - it's a playback function

🎵 **Audio Control:**
- stop_audio() - Stop currently playing audio
- get_available_voices(language_filter) - Get available voices with optional language filter

**Key Features:**
- Automatic audio caching in fixed directory (tts_audio_cache/)
- Intelligent text chunking for long texts (fixed 1200 characters)
- Only supports macOS and Windows systems
- High-quality Edge TTS voices with retry mechanism
- Cache reuse for identical text+voice combinations (plays from cache instantly)

**Popular Voices:**
- Chinese: zh-CN-XiaoxiaoNeural (晓晓-女声), zh-CN-YunxiNeural (云希-男声)
- English: en-US-AriaNeural (Aria-女声), en-US-GuyNeural (Guy-男声)

**Important Notes:**
- text_to_speech is a PLAYBACK function - it always plays audio
- Audio files are automatically cached and reused for same text+voice
- System compatibility: macOS and Windows only
- For long texts, automatic chunking will be applied

When users want to hear text spoken, use text_to_speech function. This will either play from cache (if exists) or generate new audio and play it.""",
        llm_model="default_llm",
    ),

    # Master agent to coordinate
    oxy.ReActAgent(
        is_master=True,
        name="master_agent",
        sub_agents=["tts_agent"],
        system_prompt="""You may get several types of tasks, please choose correct tools to finish tasks.""",
        llm_model="default_llm",
    ),
]


async def main():
    """Main function to run the TTS test demo"""
    
    # Start the MAS with optimized TTS capabilities
    async with MAS(oxy_space=oxy_space) as mas:
        print("🎤 TTS MCP Service with Auto-Caching Started!")
        print("=" * 60)
        print("🚀 Key Features:")
        print("- Automatic audio caching in tts_audio_cache/")
        print("- Intelligent text chunking (fixed 1200 characters)")
        print("- macOS and Windows support only")
        print("- Enhanced error handling and retry mechanism")
        print("- High-quality Edge TTS voices")
        print("- Cache reuse for identical text+voice combinations")
        print("=" * 60)
        print("📝 Test Commands:")
        print("- '读这段文字：你好世界' - Play Chinese text as speech")
        print("- 'Read this aloud: Hello world' - Play English text as speech")
        print("- 'What voices are available?' - Show available voices")
        print("- 'Stop audio' - Stop current playback")
        print("- '播放这段话：[your text]' - Direct speech playback")
        print("- 'Play this text: [your text]' - Direct speech playback")
        print("=" * 60)
        
        await mas.start_web_service(
            first_query="Hello! I'm your TTS assistant with automatic caching. I can convert text to speech, cache audio files for reuse, and play them back. I support Chinese and English voices on macOS and Windows. What would you like me to help you with?",
            welcome_message="Hi, I'm OxyGent with TTS and auto-caching capabilities. How can I assist you?",
        )


if __name__ == "__main__":
    # Install dependencies reminder
    print("🎵 Optimized TTS MCP Service Test Demo")
    print("=" * 40)
    print("📦 Required dependencies:")
    print("pip install edge-tts pydub")
    print("🔧 Optional (for high-quality audio merging):")
    print("brew install ffmpeg  # macOS")
    print("apt install ffmpeg   # Linux")
    print("=" * 40)
    print()
    
    asyncio.run(main())
