"""Edge TTS — Microsoft Fast Neural voices via the free edge-tts package.

Default voice: en-US-ChristopherNeural. No API key required.
Install: pip install edge-tts
"""
from __future__ import annotations

import asyncio
from pathlib import Path

try:
    import edge_tts
except ImportError:  # pragma: no cover
    edge_tts = None

# Alias map — the selector / pipeline can pass a short name or the full voice id.
VOICES = {
    "christopher": "en-US-ChristopherNeural",
    "guy": "en-US-GuyNeural",
    "jenny": "en-US-JennyNeural",
    "aria": "en-US-AriaNeural",
    "eric": "en-US-EricNeural",
    "michelle": "en-US-MichelleNeural",
    "roger": "en-US-RogerNeural",
    "steffan": "en-US-SteffanNeural",
}


class EdgeTTS:
    """Minimal TTS provider that matches the OpenMontage tool contract.

    ``execute(inputs)`` accepts the same keys the other TTS tools use:
    ``text``, ``voice_id`` (alias ``voice``), ``rate``, ``output_path``.
    """

    name = "edge_tts"
    capability = "tts"
    provider = "edge"

    def _available(self) -> bool:
        return edge_tts is not None

    def execute(self, inputs: dict) -> dict:
        if not self._available():
            return {
                "success": False,
                "error": "edge-tts is not installed. Run: pip install edge-tts",
            }

        text = (inputs.get("text") or "").strip()
        if not text:
            return {"success": False, "error": "No text supplied to edge_tts."}

        raw_voice = inputs.get("voice_id") or inputs.get("voice") or "christopher"
        voice_id = VOICES.get(raw_voice, raw_voice)
        rate = inputs.get("rate", "+0%")          # "-4%" for slower narration
        out = Path(inputs["output_path"])
        out.parent.mkdir(parents=True, exist_ok=True)

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text=text, voice=voice_id, rate=rate
            )
            await communicate.save(str(out))

        try:
            asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": f"edge-tts failed: {exc}"}

        return {
            "success": True,
            "data": {
                "output_path": str(out),
                "voice_id": voice_id,
                "provider": "edge",
                "chars": len(text),
                "cost_usd": 0.0,
            },
        }


# OpenMontage's registry also accepts a module-level ``AVAILABLE`` flag.
AVAILABLE = edge_tts is not None
