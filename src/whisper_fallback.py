"""Opt-in local Whisper fallback (CPU, faster-whisper). Imported lazily only when enabled."""
from __future__ import annotations
import io, threading
_model = None; _lock = threading.Lock()


def _decode(data: bytes):
    import av, numpy as np
    out = []
    with av.open(io.BytesIO(data)) as c:
        st = next((s for s in c.streams if s.type == "audio"), None)
        if st is None:
            return None
        rs = av.AudioResampler(format="flt", layout="mono", rate=16000)
        for fr in c.decode(st):
            for f in rs.resample(fr):
                out.append(f.to_ndarray().reshape(-1))
        for f in rs.resample(None):
            out.append(f.to_ndarray().reshape(-1))
    return np.concatenate(out).astype("float32") if out else None


def transcribe(data: bytes, model_size: str = "base", language: str | None = None) -> dict | None:
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(model_size, device="cpu", compute_type="int8")
        audio = _decode(data)
        if audio is None or len(audio) < 16000 * 0.5:
            return None
        segs, info = _model.transcribe(audio, vad_filter=True, beam_size=1, language=language)
        segs = [{"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()} for s in segs if s.text.strip()]
        return {"segments": segs, "language": info.language, "languageProbability": round(info.language_probability, 3)}
