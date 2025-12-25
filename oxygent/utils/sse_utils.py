import aiohttp
from typing import AsyncIterator, Dict, Any, Optional
async def iter_sse_events(
    resp: aiohttp.ClientResponse,
    *,
    chunk_size: int = 8 * 1024,
    max_buffer_bytes: int = 2 * 1024 * 1024,  # 2 MiB total buffered (anti-DoS)
    max_event_bytes: int = 512 * 1024,  # 512 KiB per event block (anti-DoS)
    max_data_bytes: int = 512 * 1024,  # 512 KiB of accumulated "data:" per event
    allow_partial_final_event: bool = True,  # flush remaining bytes on EOF
) -> AsyncIterator[Dict[str, Any]]:
    """
    Parse an HTTP response body as a Server-Sent Events (SSE) stream.

    Yields dicts:
        {
            "event": str | None,
            "data": str,
            "id": str | None,
            "retry": int | None,
        }

    Security/robustness hardening:
    - Caps buffer size to mitigate memory/CPU DoS if delimiters never arrive.
    - Caps per-event size and per-event data size.
    - Best-effort flush of the final event on EOF (optional).
    - Ignores `id` values containing NUL (\\x00).
    - Accepts `retry` only if non-negative int.
    """

    def _parse_event_block(raw: bytes) -> Optional[Dict[str, Any]]:
        # Trim leading/trailing newlines within the event block.
        raw = raw.strip(b"\n")
        if not raw:
            return None

        event_type: Optional[str] = None
        event_id: Optional[str] = None
        retry: Optional[int] = None
        data_lines: list[str] = []
        data_bytes = 0

        for line in raw.split(b"\n"):
            # Comment/heartbeat lines start with ":" and should be ignored.
            if line.startswith(b":"):
                continue

            # Field parsing:
            # - "field:value"
            # - "field:" (empty value)
            # - "field" (empty value)
            if b":" in line:
                field_b, value_b = line.split(b":", 1)
                if value_b.startswith(b" "):
                    value_b = value_b[1:]
            else:
                field_b, value_b = line, b""

            # Empty field names are ignored in practice.
            if not field_b:
                continue

            field = field_b.decode("utf-8", errors="replace")

            if field == "event":
                event_type = value_b.decode("utf-8", errors="replace")

            elif field == "data":
                # Cap total event data bytes (prevents huge multi-line data DoS).
                data_bytes += len(value_b)
                if data_bytes > max_data_bytes:
                    raise ValueError(
                        f"SSE event data too large (> {max_data_bytes} bytes)"
                    )
                data_lines.append(value_b.decode("utf-8", errors="replace"))

            elif field == "id":
                # Ignore IDs containing NUL (common interoperability/safety behavior).
                if b"\x00" in value_b:
                    continue
                event_id = value_b.decode("utf-8", errors="replace")

            elif field == "retry":
                try:
                    n = int(value_b.decode("utf-8", errors="replace"))
                    if n >= 0:
                        retry = n
                except ValueError:
                    pass

        # Skip blocks that contain no meaningful fields (e.g., only comments).
        if event_type is None and event_id is None and retry is None and not data_lines:
            return None

        return {
            "event": event_type,
            "data": "\n".join(data_lines),
            "id": event_id,
            "retry": retry,
        }

    buf = bytearray()

    async for chunk in resp.content.iter_chunked(chunk_size):
        if not chunk:
            continue

        # Normalize newlines to LF ("\n") safely across chunk boundaries.
        if buf and buf[-1] == 0x0D:  # '\r'
            if chunk[:1] == b"\n":
                buf[-1] = 0x0A  # '\n'
                chunk = chunk[1:]
            else:
                buf[-1] = 0x0A  # '\n'

        # Normalize inside this chunk.
        chunk = chunk.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        buf.extend(chunk)

        # Total buffer cap (anti-DoS).
        if len(buf) > max_buffer_bytes:
            raise ValueError(
                f"SSE buffer too large (> {max_buffer_bytes} bytes); delimiter not found"
            )

        while True:
            # After normalization, SSE events are separated by "\n\n".
            sep = buf.find(b"\n\n")
            if sep == -1:
                break

            # Per-event cap before copying bytes out.
            if sep > max_event_bytes:
                raise ValueError(f"SSE event too large (> {max_event_bytes} bytes)")

            raw = bytes(buf[:sep])
            del buf[: sep + 2]  # consume the delimiter too

            evt = _parse_event_block(raw)
            if evt is not None:
                yield evt

    # EOF flush: normalize trailing '\r' that never got paired.
    if buf and buf[-1] == 0x0D:
        buf[-1] = 0x0A

    if allow_partial_final_event and buf:
        if len(buf) > max_event_bytes:
            raise ValueError(f"SSE final event too large (> {max_event_bytes} bytes)")
        evt = _parse_event_block(bytes(buf))
        if evt is not None:
            yield evt