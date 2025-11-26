"""
Simplified TTS MCP Server for macOS and Windows
Features:
- Text-to-speech with intelligent chunking
- Automatic audio caching with fixed storage location
- Simple playback control (play/stop only)
- macOS and Windows only support
"""

import asyncio
import os
import tempfile
import threading
import time
import re
import random
import subprocess
import platform
import shutil
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, asdict

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    import warnings
    # Suppress pydub warnings about ffmpeg/ffprobe
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

from mcp.server.fastmcp import FastMCP
from pydantic import Field

# Initialize FastMCP server instance
mcp = FastMCP()

# Fixed configuration parameters
FIXED_CHUNK_SIZE = 1200    # Fixed chunk size for text splitting
MIN_CHUNK_SIZE = 50        # Minimum characters per chunk
MAX_RETRIES = 3            # Maximum retry attempts
BASE_DELAY = 1.0           # Base delay time (seconds)
MAX_DELAY = 10.0           # Maximum delay time (seconds)

# Fixed cache directory in current working directory
FIXED_AUDIO_DIR = os.path.join(os.getcwd(), "tts_audio_cache")
MAX_CACHE_FILES = 50       # Increased cache size since it's permanent storage
CACHE_RETENTION_HOURS = 168 # 1 week retention

# Cache for voices to avoid repeated API calls
_voices_cache = None
_cache_timestamp = 0
CACHE_DURATION = 3600  # 1 hour in seconds

# Audio playback state management
_current_audio_process = None
_audio_lock = threading.Lock()

# Simplified playback info
_current_playback_info = None
_playback_control_lock = threading.Lock()

# Dependency check cache
_dependency_check_result = None
_dependency_check_timestamp = 0
_dependency_check_completed = False  # Flag to indicate if initial check is done
DEPENDENCY_CHECK_CACHE_DURATION = 3600 * 24  # 24 hours cache for system dependencies


def check_system_dependencies(use_cache: bool = True, force_refresh: bool = False) -> tuple[bool, str]:
    """
    Check all system dependencies required for TTS functionality with intelligent caching
    Args:
        use_cache: Whether to use cached results (default: True)
        force_refresh: Force a fresh check even if cache is valid (default: False)
    Returns: (is_ready, error_message)
    """
    global _dependency_check_result, _dependency_check_timestamp, _dependency_check_completed
    
    # If we have a successful check and it's not forced refresh, use permanent cache
    if (use_cache and not force_refresh and _dependency_check_completed and 
        _dependency_check_result is not None and _dependency_check_result[0]):
        return _dependency_check_result
    
    # For failed checks or time-based cache, check expiration
    current_time = time.time()
    if (use_cache and not force_refresh and _dependency_check_result is not None and 
        (current_time - _dependency_check_timestamp) < DEPENDENCY_CHECK_CACHE_DURATION):
        return _dependency_check_result
    
    errors = []
    
    # 1. Check system compatibility
    system = platform.system().lower()
    if system not in ["darwin", "windows"]:
        errors.append(f"""❌ Unsupported system: {platform.system()}
   🖥️  Supported systems: macOS (Darwin) and Windows only
   🔧 Solution: Use this TTS tool on macOS or Windows
   📖 Reason: Audio playback requires system-specific commands (afplay/PowerShell)""")
    
    # 2. Check edge-tts availability
    if not EDGE_TTS_AVAILABLE:
        errors.append("""❌ edge-tts is not installed
   📦 Installation: pip install edge-tts
   📖 Description: Microsoft Edge Text-to-Speech library for voice synthesis""")
    
    # 3. Check audio player availability (only if system is supported)
    if not errors:  # Only check if system is supported
        player_cmd = get_audio_player()
        if not player_cmd:
            errors.append(f"❌ No suitable audio player found for {platform.system()}")
        else:
            # Test audio player command
            if system == "darwin":
                # Test afplay
                try:
                    result = subprocess.run(["which", "afplay"], capture_output=True, timeout=5)
                    if result.returncode != 0:
                        errors.append("""❌ afplay command not found on macOS
   🔧 Solution: afplay should be pre-installed on macOS
   🩺 Diagnosis: Check if macOS audio system is working properly""")
                except Exception as e:
                    errors.append(f"""❌ Failed to verify afplay: {e}
   🔧 Solution: Restart Terminal or check macOS audio system""")
            elif system == "windows":
                # Test PowerShell availability
                try:
                    subprocess.run(["powershell", "-c", "exit"], capture_output=True, check=True, timeout=2)
                except Exception:
                    errors.append("""❌ PowerShell not available on Windows
   🔧 Solution: PowerShell should be pre-installed on Windows 10/11
   🩺 Diagnosis: Check Windows PowerShell installation""")
    
    # 4. Check cache directory permissions
    try:
        os.makedirs(FIXED_AUDIO_DIR, exist_ok=True)
        # Test write permission
        test_file = os.path.join(FIXED_AUDIO_DIR, ".test_write")
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
    except Exception as e:
        errors.append(f"""❌ Cannot write to cache directory {FIXED_AUDIO_DIR}
   🔧 Solution: Check directory permissions or change working directory
   📁 Error: {e}""")
    
    # 5. Optional: Check pydub and ffmpeg (for advanced features)
    warnings = []
    if not PYDUB_AVAILABLE:
        warnings.append("""⚠️  pydub not available - audio effects and duration detection disabled
   📦 Optional installation: pip install pydub
   📖 Description: Audio processing library for speed/volume control""")
    else:
        # Check ffmpeg for high-quality audio merging
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True, timeout=5)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            warnings.append("""⚠️  ffmpeg not found - will use basic audio merging
   📦 Optional installation: 
      macOS: brew install ffmpeg
      Windows: Download from https://ffmpeg.org/
      Linux: apt install ffmpeg
   📖 Description: High-quality audio processing for long text synthesis""")
    
    # Prepare result
    if errors:
        error_msg = "🚨 TTS System Dependencies Check Failed:\n\n" + "\n\n".join(errors)
        
        # Add installation summary
        installation_summary = []
        if not EDGE_TTS_AVAILABLE:
            installation_summary.append("pip install edge-tts")
        if not PYDUB_AVAILABLE:
            installation_summary.append("pip install pydub  # Optional")
        
        if installation_summary:
            error_msg += f"\n\n📋 Quick Installation Summary:\n   " + "\n   ".join(installation_summary)
        
        if warnings:
            error_msg += "\n\n⚠️  Additional Warnings:\n\n" + "\n\n".join(warnings)
        
        error_msg += "\n\n💡 After installing dependencies, restart your application to take effect."
        result = (False, error_msg)
    else:
        # All critical dependencies are available
        success_msg = "✅ TTS System Ready"
        if warnings:
            success_msg += "\n\nWarnings:\n" + "\n".join(warnings)
        result = (True, success_msg)
    
    # Cache the result
    _dependency_check_result = result
    _dependency_check_timestamp = current_time
    
    # Mark as completed if successful (enables permanent caching)
    if result[0]:  # If dependencies check passed
        _dependency_check_completed = True
        print("✅ System dependencies verified - using permanent cache for future checks")
    
    return result


def validate_dependencies() -> Optional[str]:
    """
    Validate dependencies and return error message if not ready, None if ready
    """
    is_ready, message = check_system_dependencies()
    return None if is_ready else f"Dependency Check Failed:\n{message}"


@dataclass
class PlaybackInfo:
    """Information about current audio playback"""
    original_file: str
    current_file: str
    process: subprocess.Popen
    start_time: float
    duration: Optional[float] = None
    current_speed: float = 1.0
    current_volume: float = 1.0


@dataclass
class CacheEntry:
    """Represents a cached audio file entry"""
    file_id: str
    text_hash: str
    voice: str
    file_path: str
    created_at: datetime
    file_size: int
    text_preview: str  # First 50 characters of original text
    playback_count: int = 0
    last_played: Optional[datetime] = None


class AudioCache:
    """Manages audio file caching in fixed directory"""
    
    def __init__(self):
        self.cache_file = os.path.join(FIXED_AUDIO_DIR, "cache_index.json")
        self._ensure_cache_dir()
        self._load_cache_index()
    
    def _ensure_cache_dir(self):
        """Ensure cache directory exists"""
        os.makedirs(FIXED_AUDIO_DIR, exist_ok=True)
    
    def _load_cache_index(self):
        """Load cache index from file"""
        self.entries: Dict[str, CacheEntry] = {}
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for entry_data in data:
                        entry = CacheEntry(
                            file_id=entry_data['file_id'],
                            text_hash=entry_data['text_hash'],
                            voice=entry_data['voice'],
                            file_path=entry_data['file_path'],
                            created_at=datetime.fromisoformat(entry_data['created_at']),
                            file_size=entry_data['file_size'],
                            text_preview=entry_data['text_preview'],
                            playback_count=entry_data.get('playback_count', 0),
                            last_played=datetime.fromisoformat(entry_data['last_played']) if entry_data.get('last_played') else None
                        )
                        self.entries[entry_data['file_id']] = entry
            except Exception as e:
                print(f"Error loading cache index: {e}")
                self.entries = {}
    
    def _save_cache_index(self):
        """Save cache index to file"""
        try:
            data = []
            for entry in self.entries.values():
                entry_data = asdict(entry)
                entry_data['created_at'] = entry.created_at.isoformat()
                if entry.last_played:
                    entry_data['last_played'] = entry.last_played.isoformat()
                else:
                    entry_data['last_played'] = None
                data.append(entry_data)
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving cache index: {e}")
    
    def _generate_text_hash(self, text: str, voice: str) -> str:
        """Generate hash for text and voice combination"""
        content = f"{text}:{voice}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _cleanup_expired_entries(self):
        """Remove expired cache entries"""
        cutoff_time = datetime.now() - timedelta(hours=CACHE_RETENTION_HOURS)
        expired_entries = []
        
        for file_id, entry in self.entries.items():
            if entry.created_at < cutoff_time:
                expired_entries.append(file_id)
        
        for file_id in expired_entries:
            self._remove_entry(file_id)
    
    def _cleanup_excess_files(self):
        """Remove excess files (keep only MAX_CACHE_FILES newest)"""
        if len(self.entries) > MAX_CACHE_FILES:
            # Sort by creation time, oldest first
            entries_list = list(self.entries.items())
            entries_list.sort(key=lambda x: x[1].created_at)
            excess_count = len(entries_list) - MAX_CACHE_FILES
            
            for i in range(excess_count):
                file_id = entries_list[i][0]
                self._remove_entry(file_id)
    
    def _remove_entry(self, file_id: str):
        """Remove a cache entry and its file"""
        if file_id in self.entries:
            entry = self.entries[file_id]
            try:
                if os.path.exists(entry.file_path):
                    os.remove(entry.file_path)
            except Exception as e:
                print(f"Error removing cached file {entry.file_path}: {e}")
            del self.entries[file_id]
    
    def find_cached_audio(self, text: str, voice: str) -> Optional[CacheEntry]:
        """Find cached audio for given text and voice"""
        self._cleanup_expired_entries()
        text_hash = self._generate_text_hash(text, voice)
        
        for entry in self.entries.values():
            if (entry.text_hash == text_hash and 
                os.path.exists(entry.file_path)):
                return entry
        return None
    
    def add_to_cache(self, text: str, voice: str, file_path: str) -> str:
        """Add audio file to cache"""
        self._cleanup_expired_entries()
        self._cleanup_excess_files()
        
        file_id = str(uuid.uuid4())
        text_hash = self._generate_text_hash(text, voice)
        
        # Copy file to fixed cache directory
        cached_file_path = os.path.join(FIXED_AUDIO_DIR, f"{file_id}.mp3")
        shutil.copy2(file_path, cached_file_path)
        
        # Create cache entry
        entry = CacheEntry(
            file_id=file_id,
            text_hash=text_hash,
            voice=voice,
            file_path=cached_file_path,
            created_at=datetime.now(),
            file_size=os.path.getsize(cached_file_path),
            text_preview=text[:50] + "..." if len(text) > 50 else text
        )
        
        self.entries[file_id] = entry
        self._save_cache_index()
        return file_id
    
    def get_cached_file(self, file_id: str) -> Optional[CacheEntry]:
        """Get cached file by ID"""
        if file_id in self.entries:
            entry = self.entries[file_id]
            if os.path.exists(entry.file_path):
                return entry
        return None
    
    def update_playback_stats(self, file_id: str):
        """Update playback statistics"""
        if file_id in self.entries:
            self.entries[file_id].playback_count += 1
            self.entries[file_id].last_played = datetime.now()
            self._save_cache_index()


# Global cache instance
audio_cache = AudioCache()


def get_audio_player():
    """Get the appropriate audio player command for macOS and Windows only"""
    system = platform.system().lower()
    
    if system == "darwin":  # macOS
        return ["afplay"]
    elif system == "windows":
        # Try different Windows audio players in order of preference
        # First try Windows Media Player
        try:
            subprocess.run(["powershell", "-c", "exit"], capture_output=True, check=True, timeout=2)
            return ["powershell", "-c", "(New-Object Media.SoundPlayer '%s').PlaySync()"]
        except:
            # Fallback to start command (opens with default audio player)
            return ["cmd", "/c", "start", "/wait", ""]
    else:
        # Unsupported system
        return None


def get_audio_duration(file_path: str) -> Optional[float]:
    """Get audio file duration in seconds using pydub"""
    if not PYDUB_AVAILABLE:
        return None
    
    try:
        audio = AudioSegment.from_file(file_path)
        return len(audio) / 1000.0  # Convert milliseconds to seconds
    except Exception as e:
        print(f"Error getting audio duration: {e}")
        return None


def apply_audio_effects(input_file: str, output_file: str, speed: float = 1.0, volume: float = 1.0) -> bool:
    """Apply audio effects (speed and volume) using pydub"""
    if not PYDUB_AVAILABLE:
        # If pydub not available, just copy the file
        shutil.copy2(input_file, output_file)
        return True
    
    try:
        audio = AudioSegment.from_file(input_file)
        
        # Apply volume adjustment
        if volume != 1.0:
            # Convert to dB (20 * log10(volume))
            volume_db = 20 * (volume ** 0.5 - 1) if volume < 1.0 else 20 * (volume - 1)
            audio = audio + volume_db
        
        # Apply speed adjustment
        if speed != 1.0:
            # Change speed by manipulating frame rate
            audio = audio._spawn(audio.raw_data, overrides={"frame_rate": int(audio.frame_rate * speed)})
            audio = audio.set_frame_rate(audio.frame_rate)
        
        audio.export(output_file, format="mp3")
        return True
        
    except Exception as e:
        print(f"Error applying audio effects: {e}")
        # Fallback: copy original file
        shutil.copy2(input_file, output_file)
        return False


def play_audio_file_sync(filepath: str, speed: float = 1.0, volume: float = 1.0) -> bool:
    """Play an audio file synchronously with speed and volume control"""
    global _current_audio_process, _current_playback_info
    
    if not os.path.exists(filepath):
        print(f"Audio file not found: {filepath}")
        return False
    
    player_cmd = get_audio_player()
    if not player_cmd:
        system = platform.system()
        print(f"No suitable audio player found. System '{system}' is not supported. Only macOS and Windows are supported.")
        return False
    
    # Apply audio effects if needed
    final_file = filepath
    if speed != 1.0 or volume != 1.0:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
        temp_file.close()
        if apply_audio_effects(filepath, temp_file.name, speed, volume):
            final_file = temp_file.name
        else:
            final_file = filepath
    
    try:
        # Stop any currently playing audio first
        stop_audio_playback()
        
        # Prepare command
        if platform.system().lower() == "windows":
            if "powershell" in player_cmd[0]:
                # PowerShell Media.SoundPlayer format
                cmd = [player_cmd[0], player_cmd[1], player_cmd[2] % final_file]
            else:
                # cmd start format
                cmd = player_cmd + [final_file]
        else:
            cmd = player_cmd + [final_file]
        
        print(f"Audio command: {cmd}")
        
        print(f"Starting audio playback: {final_file} (speed: {speed}x, volume: {volume})")
        
        # Start playback with better error handling
        try:
            # Don't use preexec_fn on macOS as it can cause issues
            if platform.system().lower() == "windows":
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            else:
                # macOS - use simple Popen without preexec_fn
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            print(f"Audio process started with PID: {process.pid}")
        except Exception as e:
            print(f"Failed to start audio process: {e}")
            print(f"Command that failed: {cmd}")
            return False
        
        # Get duration
        duration = get_audio_duration(final_file)
        if duration:
            print(f"Audio duration: {duration:.1f} seconds")
        
        # Update the global state with lock
        with _playback_control_lock:
            # Create playback info
            _current_playback_info = PlaybackInfo(
                original_file=filepath,
                current_file=final_file,
                process=process,
                start_time=time.time(),
                duration=duration,
                current_speed=speed,
                current_volume=volume
            )
            
            # Keep reference for backward compatibility
            _current_audio_process = process
        
        print(f"Audio playback started successfully")
        
        # For macOS afplay, wait for the process to complete (it's synchronous)
        # For Windows, the process may return immediately
        if platform.system().lower() == "darwin":
            # Wait for afplay to finish (it plays synchronously)
            try:
                returncode = process.wait(timeout=300)  # 5 minute timeout
                if returncode != 0:
                    print(f"Warning: Audio process exited with code: {returncode}")
                    # Try to get error output
                    try:
                        stdout, stderr = process.communicate(timeout=1)
                        if stderr:
                            print(f"Process stderr: {stderr.decode()}")
                        if stdout:
                            print(f"Process stdout: {stdout.decode()}")
                    except:
                        pass
                else:
                    print("Audio playback completed successfully")
            except subprocess.TimeoutExpired:
                print("Audio playback timeout (>5 minutes)")
                process.kill()
        else:
            # Windows - check if process started successfully
            time.sleep(0.5)
            if process.poll() is not None:
                print(f"Warning: Audio process exited immediately with code: {process.returncode}")
                # Try to get error output
                try:
                    stdout, stderr = process.communicate(timeout=1)
                    if stderr:
                        print(f"Process stderr: {stderr.decode()}")
                    if stdout:
                        print(f"Process stdout: {stdout.decode()}")
                except:
                    pass
        
        # Clean up temporary file after playback completes
        if final_file != filepath:
            def cleanup():
                # Wait a bit more to ensure file is not in use
                time.sleep(2)
                try:
                    if os.path.exists(final_file):
                        os.unlink(final_file)
                        print(f"Cleaned up temporary file: {final_file}")
                except Exception as e:
                    print(f"Failed to cleanup temp file: {e}")
            threading.Thread(target=cleanup, daemon=True).start()
        
        return True
        
    except Exception as e:
        print(f"Error playing audio: {e}")
        return False


def stop_audio_playback():
    """Stop any currently playing audio"""
    global _current_audio_process, _current_playback_info
    
    try:
        with _playback_control_lock:
            # Handle playback info structure
            if _current_playback_info and _current_playback_info.process:
                process = _current_playback_info.process
                if process.poll() is None:
                    try:
                        print("Terminating audio process...")
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                            print("Audio process terminated gracefully")
                        except subprocess.TimeoutExpired:
                            print("Process didn't terminate, forcing kill...")
                            process.kill()
                            process.wait(timeout=1)
                            print("Audio process killed")
                    except Exception as e:
                        print(f"Error stopping audio process: {e}")
                        try:
                            process.kill()
                            process.wait(timeout=1)
                        except:
                            pass
            
            # Handle legacy audio process
            elif _current_audio_process and _current_audio_process.poll() is None:
                try:
                    print("Stopping legacy audio process...")
                    _current_audio_process.terminate()
                    try:
                        _current_audio_process.wait(timeout=3)
                        print("Legacy audio process terminated")
                    except subprocess.TimeoutExpired:
                        _current_audio_process.kill()
                        _current_audio_process.wait(timeout=1)
                        print("Legacy audio process killed")
                except Exception as e:
                    print(f"Error stopping legacy audio: {e}")
            
            # Clear playback info
            _current_playback_info = None
            _current_audio_process = None
            print("Audio playback state cleared")
            
    except Exception as e:
        print(f"Error in stop_audio_playback: {e}")
        # Force clear even if there was an error
        _current_playback_info = None
        _current_audio_process = None


def smart_text_split(text: str) -> List[str]:
    """
    Intelligent text chunking with FIXED chunk size, prioritizing splits at sentence endings,
    then at commas/semicolons, and finally forcing character-based splits
    """
    max_size = FIXED_CHUNK_SIZE  # Use fixed chunk size
    
    if len(text) <= max_size:
        return [text]
    
    chunks = []
    current_chunk = ""
    
    # Regular expression for sentence endings
    sentence_endings = re.compile(r'([。！？.!?]+)')
    sentences = sentence_endings.split(text)
    
    i = 0
    while i < len(sentences):
        sentence = sentences[i]
        
        # If current sentence plus punctuation is still within limit
        if i + 1 < len(sentences) and sentence_endings.match(sentences[i + 1]):
            sentence += sentences[i + 1]
            i += 2
        else:
            i += 1
            
        # Check if adding this sentence would exceed limit
        if len(current_chunk + sentence) <= max_size:
            current_chunk += sentence
        else:
            # Save current chunk if not empty
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
                current_chunk = ""
            
            # If single sentence exceeds limit, further split it
            if len(sentence) > max_size:
                # Split by commas and semicolons
                comma_parts = re.split(r'([，；,;]+)', sentence)
                temp_chunk = ""
                
                for part in comma_parts:
                    if len(temp_chunk + part) <= max_size:
                        temp_chunk += part
                    else:
                        if temp_chunk.strip():
                            chunks.append(temp_chunk.strip())
                        temp_chunk = part
                        
                        # If single part is still too long, force character split
                        if len(temp_chunk) > max_size:
                            while len(temp_chunk) > max_size:
                                chunks.append(temp_chunk[:max_size])
                                temp_chunk = temp_chunk[max_size:]
                
                if temp_chunk.strip():
                    current_chunk = temp_chunk
            else:
                current_chunk = sentence
    
    # Add the last chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    # Filter out chunks that are too short (except the last one)
    filtered_chunks = []
    for i, chunk in enumerate(chunks):
        if len(chunk) >= MIN_CHUNK_SIZE or i == len(chunks) - 1:
            filtered_chunks.append(chunk)
        else:
            # Merge short chunk with previous one
            if filtered_chunks:
                filtered_chunks[-1] += chunk
            else:
                filtered_chunks.append(chunk)
    
    return filtered_chunks


async def _get_voices_async():
    """Get voices asynchronously with caching"""
    global _voices_cache, _cache_timestamp
    
    current_time = time.time()
    if _voices_cache and (current_time - _cache_timestamp) < CACHE_DURATION:
        return _voices_cache
    
    try:
        voices = await edge_tts.list_voices()
        _voices_cache = voices
        _cache_timestamp = current_time
        return voices
    except Exception as e:
        print(f"Error fetching voices: {e}")
        return []


def _run_async(coro):
    """Helper function to run async code in sync context"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in an async context, create a new event loop in a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        # No event loop, create a new one
        return asyncio.run(coro)


async def synthesize_chunk(text: str, voice: str, output_file: str) -> bool:
    """
    Synthesize speech for a single text chunk with retry mechanism
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            # Text preprocessing: clean potentially problematic characters
            cleaned_text = text.strip()
            if not cleaned_text:
                print("Warning: Empty text, skipping synthesis")
                return False
            
            # Create communication object
            communicate = edge_tts.Communicate(cleaned_text, voice)
            
            # Attempt synthesis
            await communicate.save(output_file)
            
            # Verify file was created successfully and is not empty
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                return True
            else:
                raise Exception("Generated audio file is empty or does not exist")
                
        except Exception as e:
            error_msg = str(e)
            
            # Analyze error type
            if "timeout" in error_msg.lower():
                error_type = "Network timeout"
            elif "connection" in error_msg.lower():
                error_type = "Connection failed"
            elif "rate limit" in error_msg.lower():
                error_type = "Rate limit"
            elif "server" in error_msg.lower():
                error_type = "Server error"
            else:
                error_type = "Unknown error"
            
            if attempt < MAX_RETRIES:
                # Calculate delay time (exponential backoff + random jitter)
                delay = min(BASE_DELAY * (2 ** attempt) + random.uniform(0, 1), MAX_DELAY)
                print(f"Attempt {attempt + 1} failed ({error_type}: {error_msg})")
                print(f"Retrying in {delay:.1f} seconds...")
                await asyncio.sleep(delay)
            else:
                print(f"Synthesis failed after {MAX_RETRIES} retries ({error_type}: {error_msg})")
                return False
    
    return False


async def rate_limit_delay():
    """Add delay between requests to avoid rate limiting"""
    delay = random.uniform(0.5, 1.5)  # Random delay 0.5-1.5 seconds
    await asyncio.sleep(delay)


def check_ffmpeg_available() -> bool:
    """Check if ffmpeg is available"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def merge_audio_files(audio_files: List[str], output_file: str) -> bool:
    """Merge multiple audio files (intelligently choose merge method)"""
    try:
        if not audio_files:
            return False
            
        if len(audio_files) == 1:
            # Only one file, just copy it
            shutil.copy(audio_files[0], output_file)
            return True
        
        # First try using pydub (requires ffmpeg)
        if PYDUB_AVAILABLE and check_ffmpeg_available():
            try:
                print("Using high-quality merge mode (pydub + ffmpeg)")
                # Merge multiple audio files
                combined = AudioSegment.empty()
                
                for audio_file in audio_files:
                    if os.path.exists(audio_file):
                        audio = AudioSegment.from_file(audio_file)
                        combined += audio
                        # Add brief pause (optional)
                        combined += AudioSegment.silent(duration=200)  # 200ms pause
                
                # Export merged audio
                combined.export(output_file, format="mp3")
                return True
                
            except Exception as e:
                print(f"pydub merge failed: {e}")
        
        # Fallback: simple binary merge
        print("Using simple merge mode")
        with open(output_file, 'wb') as outfile:
            for audio_file in audio_files:
                if os.path.exists(audio_file):
                    with open(audio_file, 'rb') as infile:
                        data = infile.read()
                        outfile.write(data)
        
        return True
        
    except Exception as e:
        print(f"Audio merge failed: {e}")
        return False


async def synthesize_long_text(text: str, voice: str, output_file: str) -> bool:
    """
    Synthesize long text with automatic chunking using FIXED chunk size, retry mechanism and delay control
    """
    print(f"Text length: {len(text)} characters")
    
    # Process in chunks using fixed chunk size
    chunks = smart_text_split(text)
    print(f"Split into {len(chunks)} chunks for processing (fixed chunk size: {FIXED_CHUNK_SIZE})")
    
    if len(chunks) == 1:
        # Text is not too long, synthesize directly
        print("Text length is moderate, synthesizing directly...")
        return await synthesize_chunk(text, voice, output_file)
    
    # Create temporary directory for chunk audio files
    temp_dir = tempfile.mkdtemp()
    temp_files = []
    failed_chunks = []
    
    try:
        # Synthesize each chunk
        for i, chunk in enumerate(chunks, 1):
            print(f"\nProcessing chunk {i}/{len(chunks)} (length: {len(chunk)} characters)...")
            temp_file = os.path.join(temp_dir, f"chunk_{i:03d}.mp3")
            
            # Add request delay (except for first request)
            if i > 1:
                await rate_limit_delay()
            
            success = await synthesize_chunk(chunk, voice, temp_file)
            if success:
                temp_files.append(temp_file)
                print(f"✓ Chunk {i} synthesis completed")
            else:
                print(f"✗ Chunk {i} synthesis failed")
                failed_chunks.append(i)
        
        # Check for failed chunks
        if failed_chunks:
            print(f"\n{len(failed_chunks)} chunks failed: {failed_chunks}")
            return False
        
        # Ensure temporary files are in order
        temp_files.sort()
        
        # Merge audio files
        print(f"\nMerging {len(temp_files)} audio files...")
        success = merge_audio_files(temp_files, output_file)
        
        if success:
            file_size = os.path.getsize(output_file) / (1024 * 1024)  # MB
            print(f"✓ Speech synthesis completed!")
            print(f"File saved to: {output_file}")
            print(f"File size: {file_size:.2f} MB")
            return True
        else:
            print("✗ Audio merge failed")
            return False
            
    except Exception as e:
        print(f"Error during processing: {e}")
        return False
        
    finally:
        # Clean up temporary files
        try:
            shutil.rmtree(temp_dir)
            print("Temporary files cleaned up")
        except Exception as e:
            print(f"Failed to clean up temporary files: {e}")
    
    return False


@mcp.tool(description="Play text as speech with automatic caching")
def text_to_speech(
    text: str = Field(description="Text to convert to speech and play"),
    voice: str = Field(description="Voice ID (e.g., 'zh-CN-XiaoxiaoNeural', 'en-US-AriaNeural')", default="zh-CN-XiaoxiaoNeural")
) -> str:
    """
    Play text as speech with intelligent caching.
    Audio files are automatically cached for reuse. If the same text with same voice 
    is requested again, plays from cache directly.
    Always plays the audio - this is a playback function.
    Only works on macOS and Windows systems.
    """
    
    # Validate dependencies first
    dep_error = validate_dependencies()
    if dep_error:
        return dep_error
    
    # Check cache first
    cached_entry = audio_cache.find_cached_audio(text, voice)
    if cached_entry:
        print(f"Found cached audio: {cached_entry.file_id}")
        
        # Update playback stats
        audio_cache.update_playback_stats(cached_entry.file_id)
        
        # Always play cached audio
        print(f"Attempting to play cached audio: {cached_entry.file_path}")
        print(f"File exists: {os.path.exists(cached_entry.file_path)}")
        print(f"System: {platform.system()}")
        
        if play_audio_file_sync(cached_entry.file_path):
            result_msg = f"Playing cached audio (voice: {voice})"
        else:
            result_msg = f"Found cached audio but playback failed"
        
        return result_msg
    
    # Generate new audio - create temporary file first
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
    temp_file.close()
    
    try:
        # Use the advanced synthesis function with fixed chunk size
        success = _run_async(synthesize_long_text(text, voice, temp_file.name))
        
        if success:
            # Add to cache (this will copy to fixed directory)
            file_id = audio_cache.add_to_cache(text, voice, temp_file.name)
            
            # Get the cached entry to get the final path
            cached_entry = audio_cache.get_cached_file(file_id)
            final_path = cached_entry.file_path if cached_entry else temp_file.name
            
            # Always play the generated audio
            print(f"Attempting to play generated audio: {final_path}")
            print(f"File exists: {os.path.exists(final_path)}")
            print(f"System: {platform.system()}")
            
            if play_audio_file_sync(final_path):
                result_msg = f"Playing generated audio (voice: {voice})"
                # Update playback stats for new cache entry
                audio_cache.update_playback_stats(file_id)
            else:
                result_msg = f"Audio generated but playback failed (voice: {voice})"
            
            return result_msg
        else:
            return "Error in Edge TTS conversion: Synthesis failed"
            
    except Exception as e:
        return f"Error in Edge TTS conversion: {str(e)}"
    finally:
        # Clean up temporary file
        try:
            os.unlink(temp_file.name)
        except:
            pass


@mcp.tool(description="Get available Edge TTS voices")
def get_available_voices(
    language_filter: Optional[str] = Field(description="Filter voices by language (e.g., 'zh', 'en', 'zh-CN'). Leave empty to show all voices.", default=None)
) -> str:
    """Get available Edge TTS voices with optional language filtering"""
    
    # Validate dependencies first
    dep_error = validate_dependencies()
    if dep_error:
        return dep_error
    
    try:
        voices = _run_async(_get_voices_async())
        
        # Handle case where language_filter might be a Field object or None
        filter_str = None
        if language_filter is not None:
            if hasattr(language_filter, 'default'):
                # It's a Field object, get the actual value
                filter_str = getattr(language_filter, 'default', None)
            else:
                # It's a regular string
                filter_str = str(language_filter) if language_filter else None
        
        if filter_str:
            filtered_voices = [v for v in voices if filter_str.lower() in v['Locale'].lower()]
        else:
            filtered_voices = voices
        
        if not filtered_voices:
            return f"No voices found for language filter: {language_filter}"
        
        result = f"Available voices ({len(filtered_voices)} found):\n"
        for voice in filtered_voices[:20]:  # Limit to first 20 voices
            result += f"- {voice['ShortName']}: {voice['DisplayName']} ({voice['Locale']})\n"
        
        if len(filtered_voices) > 20:
            result += f"... and {len(filtered_voices) - 20} more voices"
        
        return result
        
    except Exception as e:
        return f"Error fetching voices: {str(e)}"


def list_chinese_voices() -> str:
    """List Chinese voices available in Edge TTS"""
    return get_available_voices("zh")


def list_english_voices() -> str:
    """List English voices available in Edge TTS"""
    return get_available_voices("en")


@mcp.tool(description="Stop any currently playing audio")
def stop_audio() -> str:
    """
    Stop any currently playing audio and terminate the audio process.
    """
    # Validate dependencies first (but allow stop even if deps missing)
    # This is because stop should work even if system isn't fully ready
    try:
        stop_audio_playback()
        return "Audio playback stopped successfully"
    except Exception as e:
        return f"Error stopping audio: {str(e)}"


if __name__ == "__main__":
    mcp.run()
