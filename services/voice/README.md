# Voice intake (Sarvam + Pipecat)

`sarvam_client.py` -- raw Sarvam STT/TTS calls, tested and working, including a
full TTS -> STT round trip on Hinglish claim-related phrases.

`pipeline.py` -- the actual Pipecat conversation pipeline (Sarvam STT -> Groq
LLM -> Sarvam TTS, with turn-taking via Pipecat's built-in Smart Turn VAD
model). Built against pipecat-ai 1.16.0's real installed API, which differs
from what docs.pipecat.ai currently documents -- see the module docstring for
the exact discrepancy if a pipecat upgrade breaks this.

**What's verified:** `build_voice_pipeline()` constructs successfully against
the real Sarvam and Groq API keys, with all five stages (STT -> user
aggregator -> LLM -> TTS -> assistant aggregator) correctly linked, no errors,
no deprecation warnings.

**What's NOT verified:** an actual live voice conversation. That needs an audio
transport -- a microphone/speaker, a browser running Pipecat's WebRTC
transport, or a telephony bridge -- and none of those exist in this sandboxed
terminal environment. Wiring `build_voice_pipeline()` into a `PipelineTask`
with a real transport and running an actual conversation is the next thing to
do, on a machine (or in a browser) that has one.

**Not built at all:** anything connecting this to the document pipeline --
there's no code yet that takes the conversation transcript out of `context`
and turns it into a case (classify/extract/etc.), and no WhatsApp/web
integration point for starting a voice session in the first place.
