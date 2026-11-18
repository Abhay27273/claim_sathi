"""Pipecat voice conversation pipeline: Sarvam STT -> Groq LLM -> Sarvam TTS.

Built against pipecat-ai==1.16.0's ACTUAL installed API, not its public docs --
the docs site (docs.pipecat.ai) describes `pipecat.context.base.LLMContext` and
`pipecat.context.aggregators.LLMContextAggregatorPair`, neither of which exist
in the pip-installed 1.16.0 package (verified by introspecting the installed
package directly: `ModuleNotFoundError: No module named 'pipecat.context'`).
The real location in this version is
`pipecat.processors.aggregators.llm_context.LLMContext` and
`pipecat.processors.aggregators.llm_response_universal.LLMContextAggregatorPair`.
If this breaks on a future pipecat upgrade, that mismatch is why -- check the
installed version's actual module layout before trusting the docs site.

NOT live-tested end to end: building a real-time voice conversation needs an
audio transport (microphone/speaker, WebRTC, or a telephony bridge), and none
of those exist in this sandboxed terminal environment -- no audio hardware, no
browser to host a WebRTC session. What IS tested here: that the three real
services (Sarvam STT, Groq LLM, Sarvam TTS) construct successfully against the
actual API keys in .env, and that the LLMContext/pipeline assembly is
syntactically and structurally correct. Running build_voice_pipeline() end to
end with a real transport is the next thing to verify, on a machine that has
one (or via Pipecat's SmallWebRTCTransport in a browser).
"""
import os

from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService

SYSTEM_PROMPT = (
    "You are ClaimSaathi's voice intake assistant, speaking with an Indian health-"
    "insurance policyholder in Hindi, English, or Hinglish, whichever they use. "
    "Your job is ONLY to gather: what happened to their claim (rejected or "
    "underpaid), roughly when, which insurer, and whether they have the rejection "
    "letter and policy documents. Do not give legal advice, do not promise an "
    "outcome, and do not discuss anything outside insurance claim intake. Keep "
    "responses short -- this is a spoken conversation, not a written one."
)


def build_voice_pipeline(llm_model: str = "openai/gpt-oss-20b"):
    """Returns (pipeline, context) -- caller wires `pipeline` into a
    PipelineTask with a real transport (transport.input()/.output() go at the
    start/end of the processor list) and can inspect/extend `context.messages`
    afterwards for handoff into the document pipeline."""
    stt = SarvamSTTService(api_key=os.environ["SARVAM_API_KEY"])
    tts = SarvamTTSService(
        api_key=os.environ["SARVAM_API_KEY"], settings=SarvamTTSService.Settings(voice="anushka")
    )
    llm = GroqLLMService(api_key=os.environ["GROQ_API_KEY"], settings=GroqLLMService.Settings(model=llm_model))

    context = LLMContext(messages=[{"role": "system", "content": SYSTEM_PROMPT}])
    aggregators = LLMContextAggregatorPair(context)

    pipeline = Pipeline(
        [
            stt,
            aggregators.user(),
            llm,
            tts,
            aggregators.assistant(),
        ]
    )
    return pipeline, context
