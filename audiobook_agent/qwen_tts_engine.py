"""
Qwen3-TTS Engine — Direct local GPU inference for audiobook narration.

Replaces ComfyUI-based TTS with direct Python calls to the qwen-tts library.
Supports four voice modes:
- CustomVoice: 9 preset voices with instruct-based emotion/tone control
- VoiceDesign: Generate unlimited unique voices from text descriptions
- VoiceClone: Clone any voice from a 3-60 second reference audio file
- LoRA: Fine-tuned LoRA adapters for maximum voice consistency

Architecture:
- Models are loaded once and reused across all generations
- Voice clone prompts are cached per character for consistency
- Audio chunks are concatenated with configurable pauses between speakers
- LoRA mode uses two-pass batched generation to minimize adapter swaps
"""

import json
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

# Lazy imports for heavy dependencies (torch, qwen_tts, peft)
# These are imported at model load time to avoid slow startup
_Qwen3TTSModel = None
_torch = None
_PeftModel = None


def _lazy_import():
    """Lazy-import torch and qwen_tts to avoid slow startup."""
    global _Qwen3TTSModel, _torch
    if _Qwen3TTSModel is None:
        import torch
        from qwen_tts import Qwen3TTSModel
        _Qwen3TTSModel = Qwen3TTSModel
        _torch = torch


def _lazy_import_peft():
    """Lazy-import peft to avoid slow startup when not using LoRA."""
    global _PeftModel
    if _PeftModel is None:
        from peft import PeftModel
        _PeftModel = PeftModel


# ---------------------------------------------------------------------------
# Voice configuration types
# ---------------------------------------------------------------------------

class VoiceConfig:
    """Base voice configuration."""
    pass


class CustomVoiceConfig(VoiceConfig):
    """Use a built-in CustomVoice preset with instruct support."""

    def __init__(self, speaker: str = "Ryan"):
        self.type = "custom"
        self.speaker = speaker


class CloneVoiceConfig(VoiceConfig):
    """Clone a voice from a reference audio file."""

    def __init__(self, ref_audio: str, ref_text: str = ""):
        self.type = "clone"
        self.ref_audio = ref_audio
        self.ref_text = ref_text


class DesignVoiceConfig(VoiceConfig):
    """Design a voice from a text description, then freeze as clone prompt."""

    def __init__(self, description: str, sample_text: str = ""):
        self.type = "design"
        self.description = description
        self.sample_text = sample_text or "Hello, welcome to the story."


class LoRAVoiceConfig(VoiceConfig):
    """LoRA fine-tuned adapter + reference audio for maximum voice consistency.

    The adapter is applied to the Base model's talker, then a clone prompt
    is created from the reference audio. All generation happens through
    the LoRA-modified model, producing more consistent character voices.
    """

    def __init__(
        self,
        adapter_path: str,
        ref_audio: str,
        ref_text: str = "",
        character_style: str = "",
    ):
        self.type = "lora"
        self.adapter_path = adapter_path
        self.ref_audio = ref_audio
        self.ref_text = ref_text
        self.character_style = character_style


# ---------------------------------------------------------------------------
# Main TTS Engine
# ---------------------------------------------------------------------------

class QwenTTSEngine:
    """Direct Qwen3-TTS inference engine."""

    def __init__(
        self,
        device: str = "cuda",
        precision: str = "bfloat16",
        model_size: str = "1.7B",
        narrator_voice: Optional[VoiceConfig] = None,
        narration_mode: str = "single_narrator",
        pause_between_speakers_ms: int = 500,
        pause_within_speaker_ms: int = 250,
    ):
        """
        Initialize the TTS engine.

        Args:
            device: "cuda", "cpu", or "auto"
            precision: "bfloat16", "float16", or "float32"
            model_size: "1.7B" or "0.6B"
            narrator_voice: Voice config for the narrator
            narration_mode: "single_narrator", "multi_cast", or "lora"
            pause_between_speakers_ms: Silence between different speakers
            pause_within_speaker_ms: Silence between same speaker entries
        """
        self.device = device
        self.precision = precision
        self.model_size = model_size
        self.narrator_voice = narrator_voice or CustomVoiceConfig("Ryan")
        self.narration_mode = narration_mode
        self.pause_between_speakers_ms = pause_between_speakers_ms
        self.pause_within_speaker_ms = pause_within_speaker_ms

        # Models (loaded lazily)
        self._custom_voice_model = None
        self._base_model = None
        self._design_model = None

        # Voice cache: character name -> clone prompt
        self._voice_cache: dict[str, object] = {}

        # LoRA state
        self._lora_model = None
        self._lora_clone_cache: dict[str, object] = {}
        self._current_lora_speaker: str | None = None

        # Sample rate (set after first generation)
        self._sample_rate: int = 24000  # Qwen3-TTS default

    def _get_dtype(self):
        """Get torch dtype from string."""
        _lazy_import()
        dtypes = {
            "bfloat16": _torch.bfloat16,
            "float16": _torch.float16,
            "float32": _torch.float32,
        }
        return dtypes.get(self.precision, _torch.bfloat16)

    def _get_model_id(self, variant: str) -> str:
        """Get HuggingFace model ID for a variant."""
        return f"Qwen/Qwen3-TTS-12Hz-{self.model_size}-{variant}"

    def _get_attn_impl(self) -> str:
        """Get best attention implementation for the device."""
        if self.device == "cpu":
            return "sdpa"
        try:
            import flash_attn  # noqa: F401
            return "flash_attention_2"
        except ImportError:
            return "sdpa"

    def _load_custom_voice_model(self):
        """Load the CustomVoice model (9 presets with instruct)."""
        if self._custom_voice_model is not None:
            return
        _lazy_import()
        print(f"    Loading CustomVoice model ({self.model_size})...")
        start = time.time()
        self._custom_voice_model = _Qwen3TTSModel.from_pretrained(
            self._get_model_id("CustomVoice"),
            device_map=f"{self.device}:0" if self.device == "cuda" else self.device,
            dtype=self._get_dtype(),
            attn_implementation=self._get_attn_impl(),
        )
        print(f"    CustomVoice model loaded in {time.time() - start:.1f}s")

    def _load_base_model(self):
        """Load the Base model (voice cloning)."""
        if self._base_model is not None:
            return
        _lazy_import()
        print(f"    Loading Base model ({self.model_size})...")
        start = time.time()
        self._base_model = _Qwen3TTSModel.from_pretrained(
            self._get_model_id("Base"),
            device_map=f"{self.device}:0" if self.device == "cuda" else self.device,
            dtype=self._get_dtype(),
            attn_implementation=self._get_attn_impl(),
        )
        print(f"    Base model loaded in {time.time() - start:.1f}s")

    def _load_design_model(self):
        """Load the VoiceDesign model (text description -> voice)."""
        if self._design_model is not None:
            return
        _lazy_import()
        # VoiceDesign only available in 1.7B
        print("    Loading VoiceDesign model (1.7B)...")
        start = time.time()
        self._design_model = _Qwen3TTSModel.from_pretrained(
            "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            device_map=f"{self.device}:0" if self.device == "cuda" else self.device,
            dtype=self._get_dtype(),
            attn_implementation=self._get_attn_impl(),
        )
        print(f"    VoiceDesign model loaded in {time.time() - start:.1f}s")

    def design_character_voice(
        self,
        description: str,
        sample_text: str = "Hello, welcome to the story.",
        language: str = "English",
    ) -> object:
        """
        Design a unique voice from a text description, then create a
        reusable clone prompt for consistency across all lines.

        Args:
            description: Natural language voice description
                e.g. "Gruff old man, deep gravelly baritone, slow and deliberate"
            sample_text: Sample text to generate the reference audio
            language: Language for generation

        Returns:
            Reusable voice_clone_prompt object
        """
        # Step 1: Generate reference audio with VoiceDesign
        self._load_design_model()
        wavs, sr = self._design_model.generate_voice_design(
            text=sample_text,
            language=language,
            instruct=description,
        )

        # Step 2: Convert to reusable clone prompt via Base model
        self._load_base_model()
        clone_prompt = self._base_model.create_voice_clone_prompt(
            ref_audio=(wavs[0], sr),
            ref_text=sample_text,
        )

        return clone_prompt

    def create_clone_from_file(
        self,
        audio_path: str,
        transcript: str = "",
    ) -> object:
        """
        Create a reusable clone prompt from a reference audio file.

        Args:
            audio_path: Path to reference audio (WAV, MP3, M4A)
            transcript: Transcription of the reference audio

        Returns:
            Reusable voice_clone_prompt object
        """
        self._load_base_model()
        use_xvec_only = not transcript.strip()
        if use_xvec_only:
            print(f"        [clone] No ref_text — using x_vector_only mode (speaker embedding)")
        clone_prompt = self._base_model.create_voice_clone_prompt(
            ref_audio=audio_path,
            ref_text=transcript if not use_xvec_only else None,
            x_vector_only_mode=use_xvec_only,
        )
        return clone_prompt

    def _generate_custom_voice_chunk(
        self,
        text: str,
        speaker: str,
        instruct: str,
        language: str = "English",
    ) -> tuple[np.ndarray, int]:
        """Generate audio using CustomVoice preset with instruct."""
        self._load_custom_voice_model()
        wavs, sr = self._custom_voice_model.generate_custom_voice(
            text=text,
            language=language,
            speaker=speaker,
            instruct=instruct,
        )
        self._sample_rate = sr
        return wavs[0], sr

    def _generate_clone_chunk(
        self,
        text: str,
        clone_prompt: object,
        language: str = "English",
    ) -> tuple[np.ndarray, int]:
        """Generate audio using a cached clone prompt."""
        self._load_base_model()
        wavs, sr = self._base_model.generate_voice_clone(
            text=text,
            language=language,
            voice_clone_prompt=clone_prompt,
        )
        self._sample_rate = sr
        return wavs[0], sr

    def _load_lora_for_speaker(
        self,
        speaker: str,
        config: "LoRAVoiceConfig",
    ) -> object:
        """Load a LoRA adapter for a speaker and create their clone prompt.

        If this speaker's clone prompt is already cached, returns it directly.
        Otherwise loads the adapter, creates the prompt, and caches it.

        Returns:
            Reusable voice_clone_prompt object
        """
        if speaker in self._lora_clone_cache:
            return self._lora_clone_cache[speaker]

        _lazy_import()
        _lazy_import_peft()

        adapter_path = Path(config.adapter_path)
        if not (adapter_path / "adapter_config.json").exists():
            raise FileNotFoundError(
                f"No LoRA adapter found at {adapter_path}. "
                f"Train adapters first with: uv run python -m src.tts.lora_trainer"
            )

        # Load fresh base model if switching speakers
        if self._lora_model is not None and self._current_lora_speaker != speaker:
            del self._lora_model
            if self.device == "cuda":
                _torch.cuda.empty_cache()
            self._lora_model = None

        if self._lora_model is None:
            print(f"        Loading Base model for LoRA ({speaker})...")
            device_map = f"{self.device}:0" if self.device == "cuda" else self.device
            self._lora_model = _Qwen3TTSModel.from_pretrained(
                self._get_model_id("Base"),
                device_map=device_map,
                dtype=self._get_dtype(),
                attn_implementation=self._get_attn_impl(),
            )

            # Apply LoRA adapter to the talker (model.model is the inner wrapper)
            print(f"        Applying LoRA adapter: {adapter_path.name}")
            self._lora_model.model.talker = _PeftModel.from_pretrained(
                self._lora_model.model.talker, str(adapter_path),
            )
            self._lora_model.model.talker.eval()
            self._current_lora_speaker = speaker

        # Create clone prompt from reference audio
        ref_text = config.ref_text.strip() if config.ref_text else ""
        use_xvec_only = not ref_text
        if use_xvec_only:
            print(f"        [lora-clone] No ref_text — x_vector_only mode")

        clone_prompt = self._lora_model.create_voice_clone_prompt(
            ref_audio=config.ref_audio,
            ref_text=ref_text if not use_xvec_only else None,
            x_vector_only_mode=use_xvec_only,
        )

        self._lora_clone_cache[speaker] = clone_prompt
        return clone_prompt

    def _generate_lora_chunk(
        self,
        text: str,
        speaker: str,
        config: "LoRAVoiceConfig",
        language: str = "English",
    ) -> tuple[np.ndarray, int]:
        """Generate a single audio chunk using LoRA-adapted model."""
        clone_prompt = self._load_lora_for_speaker(speaker, config)
        wavs, sr = self._lora_model.generate_voice_clone(
            text=text,
            language=language,
            voice_clone_prompt=clone_prompt,
        )
        self._sample_rate = sr
        return wavs[0], sr

    def _unload_lora(self):
        """Free LoRA model VRAM."""
        if self._lora_model is not None:
            del self._lora_model
            self._lora_model = None
            self._current_lora_speaker = None
            if _torch is not None:
                _torch.cuda.empty_cache()

    def generate_chunk(
        self,
        text: str,
        speaker: str,
        instruct: str,
        voice_config: VoiceConfig,
        language: str = "English",
    ) -> tuple[np.ndarray, int]:
        """
        Generate audio for a single script chunk.

        Args:
            text: Text to synthesize
            speaker: Speaker name (for logging)
            instruct: Voice direction for TTS
            voice_config: Voice configuration (Custom, Clone, Design, or LoRA)
            language: Language for generation

        Returns:
            (audio_array, sample_rate)
        """
        if isinstance(voice_config, CustomVoiceConfig):
            return self._generate_custom_voice_chunk(
                text=text,
                speaker=voice_config.speaker,
                instruct=instruct,
                language=language,
            )
        elif isinstance(voice_config, CloneVoiceConfig):
            # Get or create clone prompt
            cache_key = f"clone:{voice_config.ref_audio}"
            if cache_key not in self._voice_cache:
                self._voice_cache[cache_key] = self.create_clone_from_file(
                    audio_path=voice_config.ref_audio,
                    transcript=voice_config.ref_text,
                )
            return self._generate_clone_chunk(
                text=text,
                clone_prompt=self._voice_cache[cache_key],
                language=language,
            )
        elif isinstance(voice_config, LoRAVoiceConfig):
            return self._generate_lora_chunk(
                text=text,
                speaker=speaker,
                config=voice_config,
                language=language,
            )
        else:
            # Fallback to CustomVoice Ryan
            return self._generate_custom_voice_chunk(
                text=text,
                speaker="Ryan",
                instruct=instruct,
                language=language,
            )

    def _create_silence(self, duration_ms: int) -> np.ndarray:
        """Create a silence array of the given duration."""
        num_samples = int(self._sample_rate * duration_ms / 1000)
        return np.zeros(num_samples, dtype=np.float32)

    def _trim_silence(self, audio: np.ndarray, top_db: float = 40.0) -> np.ndarray:
        """Trim leading/trailing silence from a chunk."""
        if audio.size == 0:
            return audio
        peak = np.max(np.abs(audio))
        if peak < 1e-10:
            return audio
        threshold = 10 ** (-top_db / 20) * peak
        above = np.where(np.abs(audio) > threshold)[0]
        if len(above) == 0:
            return audio
        return audio[above[0]:above[-1] + 1]

    def _apply_edge_fade(self, audio: np.ndarray, fade_ms: float = 5.0) -> np.ndarray:
        """Apply tiny fade-in/out to prevent click artifacts at joins."""
        fade_samples = min(int(self._sample_rate * fade_ms / 1000), len(audio) // 2)
        if fade_samples < 2:
            return audio
        audio = audio.copy()
        audio[:fade_samples] *= np.linspace(0, 1, fade_samples).astype(np.float32)
        audio[-fade_samples:] *= np.linspace(1, 0, fade_samples).astype(np.float32)
        return audio

    def _normalize_chunk(self, audio: np.ndarray, target_dbfs: float = -20.0) -> np.ndarray:
        """Normalize chunk loudness to target dBFS."""
        rms = np.sqrt(np.mean(audio ** 2))
        if rms < 1e-10:
            return audio
        target_rms = 10 ** (target_dbfs / 20)
        return (audio * (target_rms / rms)).astype(np.float32)

    def setup_voice_map(
        self,
        characters: list[dict],
        narrator_config: Optional[VoiceConfig] = None,
        lora_adapter_dir: Optional[str] = None,
        fallback_to_design: bool = True,
    ) -> dict[str, VoiceConfig]:
        """
        Build a voice map for all characters based on narration mode.

        Args:
            characters: Character list from codex
            narrator_config: Override narrator voice config
            lora_adapter_dir: Root directory for LoRA adapters (lora mode only)
            fallback_to_design: If LoRA adapter missing, fall back to VoiceDesign

        Returns:
            Dict mapping character_id (or NARRATOR) -> VoiceConfig
        """
        narrator = narrator_config or self.narrator_voice
        voice_map: dict[str, VoiceConfig] = {"NARRATOR": narrator}

        if self.narration_mode == "single_narrator":
            # All speakers use the same narrator voice
            for char in characters:
                char_key = char.get("character_id", char.get("name", "").upper().replace(" ", "_"))
                if char_key:
                    voice_map[char_key] = narrator

        elif self.narration_mode == "lora":
            # LoRA: use pre-trained adapters, fall back to VoiceDesign if missing
            adapter_root = Path(lora_adapter_dir) if lora_adapter_dir else Path("forge/lora_adapters")
            for char in characters:
                char_key = char.get("character_id", char.get("name", "").upper().replace(" ", "_"))
                if not char_key:
                    continue

                adapter_path = adapter_root / char_key.lower()
                has_adapter = (adapter_path / "adapter_config.json").exists()

                if has_adapter:
                    # Load metadata for character_style if available
                    ref_audio = str(adapter_path / "ref_sample.wav")
                    ref_text = ""
                    character_style = ""

                    ref_text_path = adapter_path / "ref_text.txt"
                    if ref_text_path.exists():
                        ref_text = ref_text_path.read_text("utf-8").strip()

                    meta_path = adapter_path / "training_meta.json"
                    if meta_path.exists():
                        try:
                            meta = json.loads(meta_path.read_text("utf-8"))
                            character_style = meta.get("character_style", "")
                        except (json.JSONDecodeError, OSError):
                            pass

                    voice_map[char_key] = LoRAVoiceConfig(
                        adapter_path=str(adapter_path),
                        ref_audio=ref_audio,
                        ref_text=ref_text,
                        character_style=character_style,
                    )
                elif fallback_to_design:
                    # No adapter — fall back to VoiceDesign (same as multi_cast)
                    voice_desc = self._get_voice_description(char)
                    voice_map[char_key] = DesignVoiceConfig(
                        description=voice_desc,
                        sample_text=f"Hello, my name is {char.get('name', 'unknown')}.",
                    )
                    print(f"    WARNING: No LoRA adapter for {char_key}, using VoiceDesign fallback")
                else:
                    print(f"    WARNING: No LoRA adapter for {char_key}, skipping")

        else:
            # multi_cast (default): design unique voices per character
            # Voice descriptions follow Alexandria formula: [register] + [tonal character]
            for char in characters:
                char_key = char.get("character_id", char.get("name", "").upper().replace(" ", "_"))
                if not char_key:
                    continue

                voice_desc = self._get_voice_description(char)
                design_config = DesignVoiceConfig(
                    description=voice_desc,
                    sample_text=f"Hello, my name is {char.get('name', 'unknown')}.",
                )
                voice_map[char_key] = design_config  # e.g. "ANTHONY_CADE"
                original_name = char.get("name", "")
                if original_name and original_name != char_key:
                    voice_map[original_name] = design_config  # e.g. "Anthony Cade"

        return voice_map

    def _get_voice_description(self, char: dict) -> str:
        """Extract or generate a voice description for a character.

        Priority: voice_design (LLM-generated) > physical.voice > auto-generated.
        """
        voice_desc = char.get("voice_design", "")

        if not voice_desc:
            phys = char.get("physical_appearance", char.get("physical", {}))
            if isinstance(phys, dict):
                voice_desc = phys.get("voice", "")

        if not voice_desc:
            gender = char.get("gender", "").lower()
            role = char.get("role", char.get("role_in_story", "")).lower()

            if gender == "male":
                register = "male baritone"
            elif gender == "female":
                register = "female mezzo-soprano"
            else:
                register = "androgynous mid-range"

            if "antagonist" in role or "villain" in role:
                tone = "dark, commanding edge"
            elif "protagonist" in role:
                tone = "grounded, firm presence"
            else:
                tone = "clear, balanced delivery"

            voice_desc = f"{register}, {tone}"

        return voice_desc

    def _resolve_voice(
        self,
        speaker: str,
        voice_config: VoiceConfig,
    ) -> VoiceConfig:
        """
        Resolve a DesignVoiceConfig into a cached clone config.
        CustomVoice and Clone configs pass through unchanged.
        """
        if not isinstance(voice_config, DesignVoiceConfig):
            return voice_config

        cache_key = f"design:{speaker}"
        if cache_key not in self._voice_cache:
            print(f"        Designing voice for {speaker}...")
            clone_prompt = self.design_character_voice(
                description=voice_config.description,
                sample_text=voice_config.sample_text,
            )
            self._voice_cache[cache_key] = clone_prompt

        # Return a special config that uses the cached clone prompt
        # We'll handle this in generate_chunk by checking the cache
        return voice_config

    def generate_scene_audio(
        self,
        audio_script: list[dict],
        voice_map: dict[str, VoiceConfig],
        output_path: Path,
        language: str = "English",
    ) -> tuple[bool, float]:
        """
        Generate audio for an entire scene from its audio script.

        For scenes with LoRA speakers, uses two-pass batched generation to
        minimize adapter swaps. Otherwise iterates sequentially.

        Args:
            audio_script: List of {speaker, text, instruct} dicts
            voice_map: Speaker name -> VoiceConfig mapping
            output_path: Path to write the output WAV file
            language: Language for generation

        Returns:
            (success, duration_seconds)
        """
        if not audio_script:
            return False, 0.0

        # Auto-detect LoRA speakers and use batched generation
        has_lora = any(
            isinstance(voice_map.get(chunk["speaker"]), LoRAVoiceConfig)
            for chunk in audio_script
        )
        if has_lora:
            return self._generate_scene_audio_batched(
                audio_script, voice_map, output_path, language,
            )

        return self._generate_scene_audio_sequential(
            audio_script, voice_map, output_path, language,
        )

    def _generate_scene_audio_sequential(
        self,
        audio_script: list[dict],
        voice_map: dict[str, VoiceConfig],
        output_path: Path,
        language: str = "English",
    ) -> tuple[bool, float]:
        """Generate scene audio sequentially (no LoRA — simple path)."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        audio_segments: list[np.ndarray] = []
        prev_speaker = None
        total_chunks = len(audio_script)

        for idx, chunk in enumerate(audio_script):
            speaker = chunk["speaker"]
            text = chunk["text"]
            instruct = chunk.get("instruct", "Neutral, even narration.")

            # Add pause between chunks
            if prev_speaker is not None:
                if speaker != prev_speaker:
                    audio_segments.append(
                        self._create_silence(self.pause_between_speakers_ms)
                    )
                else:
                    audio_segments.append(
                        self._create_silence(self.pause_within_speaker_ms)
                    )

            # Get voice config for this speaker
            voice_config = voice_map.get(speaker, voice_map.get("NARRATOR", self.narrator_voice))

            # Resolve design voices to clone prompts
            voice_config = self._resolve_voice(speaker, voice_config)

            # Generate audio
            try:
                if isinstance(voice_config, DesignVoiceConfig):
                    # Use cached clone prompt
                    cache_key = f"design:{speaker}"
                    if cache_key in self._voice_cache:
                        wav, sr = self._generate_clone_chunk(
                            text=text,
                            clone_prompt=self._voice_cache[cache_key],
                            language=language,
                        )
                    else:
                        # Fallback to CustomVoice
                        wav, sr = self._generate_custom_voice_chunk(
                            text=text,
                            speaker="Ryan",
                            instruct=instruct,
                            language=language,
                        )
                else:
                    wav, sr = self.generate_chunk(
                        text=text,
                        speaker=speaker,
                        instruct=instruct,
                        voice_config=voice_config,
                        language=language,
                    )

                # Post-process: trim silence, fade edges, normalize volume
                wav = self._trim_silence(wav)
                wav = self._apply_edge_fade(wav)
                wav = self._normalize_chunk(wav)
                audio_segments.append(wav)
                print(f"        [{idx + 1}/{total_chunks}] {speaker}: {len(text)} chars -> {len(wav) / sr:.1f}s")

            except Exception as e:
                print(f"        [{idx + 1}/{total_chunks}] {speaker}: ERROR - {e}")
                # Add a short silence as placeholder
                audio_segments.append(self._create_silence(500))

            prev_speaker = speaker

        return self._finalize_scene(audio_segments, total_chunks, output_path)

    def _generate_scene_audio_batched(
        self,
        audio_script: list[dict],
        voice_map: dict[str, VoiceConfig],
        output_path: Path,
        language: str = "English",
    ) -> tuple[bool, float]:
        """Generate scene audio with LoRA speakers batched to minimize adapter swaps.

        Strategy:
        1. Generate all non-LoRA chunks first (sequential, using engine models)
        2. For each LoRA speaker: load adapter -> generate all their chunks -> unload
        3. Stitch all chunks together in original script order with pauses
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        total_chunks = len(audio_script)

        # Pre-allocate results indexed by script position
        chunk_audio: list[np.ndarray | None] = [None] * total_chunks

        # --- Pass 1: Generate non-LoRA chunks ---
        non_lora_indices = [
            i for i, chunk in enumerate(audio_script)
            if not isinstance(voice_map.get(chunk["speaker"]), LoRAVoiceConfig)
        ]
        if non_lora_indices:
            print(f"        Pass 1: {len(non_lora_indices)} non-LoRA chunks...")

        for idx in non_lora_indices:
            chunk = audio_script[idx]
            speaker = chunk["speaker"]
            text = chunk["text"]
            instruct = chunk.get("instruct", "Neutral, even narration.")

            voice_config = voice_map.get(speaker, voice_map.get("NARRATOR", self.narrator_voice))
            voice_config = self._resolve_voice(speaker, voice_config)

            try:
                if isinstance(voice_config, DesignVoiceConfig):
                    cache_key = f"design:{speaker}"
                    if cache_key in self._voice_cache:
                        wav, sr = self._generate_clone_chunk(
                            text=text,
                            clone_prompt=self._voice_cache[cache_key],
                            language=language,
                        )
                    else:
                        wav, sr = self._generate_custom_voice_chunk(
                            text=text, speaker="Ryan", instruct=instruct, language=language,
                        )
                else:
                    wav, sr = self.generate_chunk(
                        text=text, speaker=speaker, instruct=instruct,
                        voice_config=voice_config, language=language,
                    )
                wav = self._trim_silence(wav)
                wav = self._apply_edge_fade(wav)
                wav = self._normalize_chunk(wav)
                print(f"        [{idx + 1}/{total_chunks}] {speaker}: {len(text)} chars -> {len(wav) / sr:.1f}s")
            except Exception as e:
                print(f"        [{idx + 1}/{total_chunks}] {speaker}: ERROR - {e}")
                wav = np.zeros(int(self._sample_rate * 0.5), dtype=np.float32)

            chunk_audio[idx] = wav

        # --- Pass 2: Generate LoRA chunks, batched by speaker ---
        lora_speakers: dict[str, LoRAVoiceConfig] = {}
        for chunk in audio_script:
            spk = chunk["speaker"]
            cfg = voice_map.get(spk)
            if isinstance(cfg, LoRAVoiceConfig) and spk not in lora_speakers:
                lora_speakers[spk] = cfg

        for speaker, lora_config in lora_speakers.items():
            speaker_indices = [
                i for i, chunk in enumerate(audio_script)
                if chunk["speaker"] == speaker
            ]
            if not speaker_indices:
                continue

            print(f"\n        Pass 2: {len(speaker_indices)} chunks for {speaker} (LoRA)...")

            for idx in speaker_indices:
                chunk = audio_script[idx]
                text = chunk["text"]

                print(f"        [{idx + 1}/{total_chunks}] {speaker}: {text[:40]}...")
                start = time.time()

                try:
                    wav, sr = self._generate_lora_chunk(
                        text=text, speaker=speaker, config=lora_config, language=language,
                    )
                    wav = self._trim_silence(wav)
                    wav = self._apply_edge_fade(wav)
                    wav = self._normalize_chunk(wav)
                except Exception as e:
                    print(f"          ERROR: {e}")
                    wav = np.zeros(int(self._sample_rate * 0.5), dtype=np.float32)

                chunk_audio[idx] = wav
                print(f"          -> {len(wav) / self._sample_rate:.1f}s ({time.time() - start:.1f}s)")

            # Free LoRA model after processing this speaker
            self._unload_lora()

        # --- Stitch all chunks in original order ---
        all_segments: list[np.ndarray] = []
        prev_speaker = None

        for idx, chunk in enumerate(audio_script):
            speaker = chunk["speaker"]
            wav = chunk_audio[idx]
            if wav is None:
                wav = np.zeros(int(self._sample_rate * 0.5), dtype=np.float32)

            if prev_speaker is not None:
                pause_ms = (
                    self.pause_between_speakers_ms if speaker != prev_speaker
                    else self.pause_within_speaker_ms
                )
                all_segments.append(self._create_silence(pause_ms))

            all_segments.append(wav)
            prev_speaker = speaker

        return self._finalize_scene(all_segments, total_chunks, output_path)

    def _finalize_scene(
        self,
        audio_segments: list[np.ndarray],
        total_chunks: int,
        output_path: Path,
    ) -> tuple[bool, float]:
        """Concatenate segments, validate, and write the output WAV."""
        if not audio_segments:
            return False, 0.0

        real_chunks = sum(1 for seg in audio_segments if np.max(np.abs(seg)) > 1e-6)
        if real_chunks == 0:
            print(f"        All {total_chunks} chunks failed — no audio generated")
            return False, 0.0

        combined = np.concatenate(audio_segments)
        duration = len(combined) / self._sample_rate

        sf.write(str(output_path), combined, self._sample_rate)
        print(f"        -> {output_path.name} ({duration:.1f}s)")

        return True, duration

    def close(self):
        """Unload all models to free VRAM."""
        self._custom_voice_model = None
        self._base_model = None
        self._design_model = None
        self._voice_cache.clear()
        self._unload_lora()
        self._lora_clone_cache.clear()
        if _torch is not None:
            try:
                _torch.cuda.empty_cache()
            except Exception:
                pass  # CUDA context may be corrupted after illegal memory access
