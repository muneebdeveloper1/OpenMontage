"""Edge TTS — Microsoft Fast Neural voices via the free `edge-tts` package.

No API key. Auto-discovered by TTSSelector because capability == "tts".

    pip install edge-tts

Default voice: en-US-ChristopherNeural.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

try:  # optional dependency — tool reports UNAVAILABLE if missing
    import edge_tts  # type: ignore
except Exception:  # pragma: no cover
    edge_tts = None


# Short alias -> full Edge voice id. A full id may also be passed directly.
VOICES: dict[str, str] = {
    "christopher": "en-US-ChristopherNeural",
    "guy": "en-US-GuyNeural",
    "eric": "en-US-EricNeural",
    "roger": "en-US-RogerNeural",
    "steffan": "en-US-SteffanNeural",
    "jenny": "en-US-JennyNeural",
    "aria": "en-US-AriaNeural",
    "michelle": "en-US-MichelleNeural",
    "ana": "en-US-AnaNeural",
}

# Free Microsoft voices, ordered by documentary-narration suitability.
RECOMMENDED_DEFAULT = "en-US-ChristopherNeural"


class EdgeTTS(BaseTool):
    name = "edge_tts"
    version = "1.0.0"
    tier = ToolTier.VOICE
    capability = "tts"
    provider = "edge"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.API  # network call, but zero cost and zero key
    dependencies = ["pkg:edge_tts"]

    install_instructions = "pip install edge-tts"

    agent_skills = ["text-to-speech"]
    capabilities = ["text_to_speech", "sentence_segmented_narration"]
    supports = {
        "offline_fallback": False,
        "multilingual": True,
        "word_timestamps": True,
        "free": True,
        "no_api_key": True,
    }
    best_for = [
        "documentary narration",
        "long-form voiceover on a zero budget",
        "Christopher / Guy / Jenny neural voices",
    ]

    resource_profile = ResourceProfile(
        cpu_cores=1,
        ram_mb=256,
        vram_mb=0,
        disk_mb=10,
        network_required=True,
    )
    retry_policy = RetryPolicy(
        max_retries=2,
        backoff_seconds=1.5,
        retryable_errors=["ConnectionError", "TimeoutError", "ClientConnectorError"],
    )

    input_schema = {
        "type": "object",
        "required": ["text", "output_path"],
        "properties": {
            "text": {"type": "string", "description": "Text to synthesize."},
            "output_path": {"type": "string", "description": "Destination .mp3 path."},
            "voice_id": {
                "type": "string",
                "description": "Alias ('christopher') or full id ('en-US-ChristopherNeural').",
            },
            "voice": {"type": "string", "description": "Alias for voice_id."},
            "rate": {
                "type": "string",
                "default": "+0%",
                "description": "Prosody rate, e.g. '-4%' for slower narration.",
            },
            "volume": {"type": "string", "default": "+0%"},
            "pitch": {"type": "string", "default": "+0Hz"},
        },
    }

    # ------------------------------------------------------------------ status
    def get_status(self):
        if edge_tts is None:
            return self._status_unavailable(
                "edge-tts is not installed. Run: pip install edge-tts"
            )
        return self._status_available()

    # --------------------------------------------------------------- execution
    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if edge_tts is None:
            return ToolResult(
                success=False,
                error="edge-tts is not installed. Run: pip install edge-tts",
            )

        text = (inputs.get("text") or "").strip()
        if not text:
            return ToolResult(success=False, error="edge_tts: 'text' is empty.")

        output_path = inputs.get("output_path")
        if not output_path:
            return ToolResult(success=False, error="edge_tts: 'output_path' is required.")

        raw_voice = inputs.get("voice_id") or inputs.get("voice") or RECOMMENDED_DEFAULT
        voice_id = VOICES.get(str(raw_voice).strip().lower(), str(raw_voice).strip())

        rate = str(inputs.get("rate", "+0%"))
        volume = str(inputs.get("volume", "+0%"))
        pitch = str(inputs.get("pitch", "+0Hz"))

        out = Path(output_path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)

        async def _render() -> None:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice_id,
                rate=rate,
                volume=volume,
                pitch=pitch,
            )
            await communicate.save(str(out))

        try:
            asyncio.run(_render())
        except RuntimeError:
            # An event loop is already running (async caller) — use a fresh loop.
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_render())
            finally:
                loop.close()
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=f"edge_tts failed: {exc}")

        if not out.is_file() or out.stat().st_size == 0:
            return ToolResult(
                success=False,
                error=f"edge_tts produced no audio at {out}",
            )

        return ToolResult(
            success=True,
            data={
                "output_path": str(out),
                "voice_id": voice_id,
                "provider": "edge",
                "model": voice_id,
                "characters": len(text),
                "rate": rate,
                "bytes": out.stat().st_size,
            },
            artifacts=[str(out)],
            cost_usd=0.0,
            model=voice_id,
        )

    # ------------------------------------------------------------------- cost
    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0


AVAILABLE = edge_tts is not None
