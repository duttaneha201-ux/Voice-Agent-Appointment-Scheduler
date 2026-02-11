"""Main Streamlit entrypoint for the Advisor Voice Agent."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

# Ensure project root is on path when running: streamlit run src/routes/app.py
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import streamlit as st

from src.config import get_settings, load_env
from src.services.actions import (
    MCPResult,
    on_booking_complete,
    on_cancel_complete,
    on_reschedule_complete,
)
from src.services.conversation_engine import (
    AgentTurn,
    ConversationSession,
    ConversationState,
)
from src.voice.stt import transcribe_audio
from src.voice.tts import text_to_speech_mp3


CHAT_KEY = "chat_history"
SESSION_KEY = "conversation_session"
MCP_RUN_FOR_KEY = "mcp_run_for_booking_code"
MCP_RESULT_KEY = "mcp_result"
LAST_VOICE_HASH_KEY = "last_processed_voice_hash"
AGENT_REPLY_TO_SPEAK_KEY = "agent_reply_to_speak"  # when set, show TTS for this reply (voice-in → voice-out)


def _init_session(timezone_label: str) -> ConversationSession:
    if SESSION_KEY not in st.session_state:
        st.session_state[SESSION_KEY] = ConversationSession(timezone_label=timezone_label)
    return st.session_state[SESSION_KEY]


def _init_history() -> None:
    if CHAT_KEY not in st.session_state:
        st.session_state[CHAT_KEY] = []  # list[tuple[role, text]]


def main() -> None:
    load_env()
    settings = get_settings()

    st.set_page_config(page_title="Advisor Appointment Voice Agent", page_icon="💬")
    st.title("Advisor Appointment Voice Agent")

    st.caption(
        "Books tentative advisor slots in a compliant, no-PII flow. "
        "**Availability:** Tue–Sat, 9am–5pm (IST), if free on your calendar."
    )

    # Start over: clear conversation and Phase 2 MCP state
    if st.button("Start over", type="secondary"):
        for key in (
            CHAT_KEY, SESSION_KEY, MCP_RUN_FOR_KEY, MCP_RESULT_KEY,
            LAST_VOICE_HASH_KEY, AGENT_REPLY_TO_SPEAK_KEY,
            "voice_recorder_turn", "pending_voice_text", "pending_voice_hash",
        ):
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

    # Initialize state
    _init_history()
    session = _init_session(timezone_label=settings.timezone)

    # Kick off greeting once at the start
    if not st.session_state[CHAT_KEY]:
        with st.spinner("Agent is starting…"):
            first_turn: AgentTurn = session.step("")
            st.session_state[CHAT_KEY].append(("agent", first_turn.text))

    # Chat history
    for role, text in st.session_state[CHAT_KEY]:
        if role == "user":
            st.markdown(f"**You:** {text}")
        else:
            st.markdown(f"**Agent:** {text}")

    # Voice: listen to last agent response (TTS)
    # When input was via voice, show agent reply as text (above) + voice (here): voice-in → text and voice out
    agent_reply_to_speak = st.session_state.get(AGENT_REPLY_TO_SPEAK_KEY)
    if agent_reply_to_speak:
        st.markdown("---")
        st.markdown("🔊 **Agent reply (audio)** — *you spoke by voice, so here is the reply in voice too*")
        with st.spinner("Generating speech…"):
            audio_bytes = text_to_speech_mp3(agent_reply_to_speak)
        if audio_bytes:
            # One player: controls + autoplay (browsers may block autoplay until interaction)
            b64 = base64.b64encode(audio_bytes).decode()
            st.markdown(
                f'<audio src="data:audio/mp3;base64,{b64}" controls autoplay></audio>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("Could not generate audio. Use *Listen to agent's last message* below to retry.")
        del st.session_state[AGENT_REPLY_TO_SPEAK_KEY]
    elif st.session_state[CHAT_KEY]:
        last_agent = next((t for r, t in reversed(st.session_state[CHAT_KEY]) if r == "agent"), None)
        if last_agent:
            if st.button("Listen to agent's last message", type="secondary"):
                audio_bytes = text_to_speech_mp3(last_agent)
                if audio_bytes:
                    st.audio(audio_bytes, format="audio/mp3")
                else:
                    st.caption("Could not generate audio.")

    # Pending voice confirmation: "You said: ..." with [Send] [Retry]
    pending_voice_text = st.session_state.get("pending_voice_text")
    if pending_voice_text:
        st.markdown("**Review your recording**")
        st.info(f"You said: {pending_voice_text}")
        st.caption("Send this to the agent or record again (Retry).")
        col_send, col_retry = st.columns(2)
        with col_send:
            if st.button("Send", type="primary", key="voice_confirm_send"):
                with st.spinner("Agent is processing..."):
                    st.session_state[CHAT_KEY].append(("user", pending_voice_text))
                    state_before = session.state
                    turn = session.step(pending_voice_text)
                    st.session_state[CHAT_KEY].append(("agent", turn.text))
                    just_confirmed = (
                        state_before == ConversationState.CONFIRMATION
                        and turn.state == ConversationState.BOOKING_COMPLETE
                    )
                    just_cancelled = (
                        state_before == ConversationState.CANCEL_CONFIRM
                        and turn.state == ConversationState.BOOKING_COMPLETE
                        and session.context.existing_booking_code
                    )
                    has_slot = (
                        session.context.chosen_slot_index is not None
                        and len(session.context.offered_slots) > session.context.chosen_slot_index
                    )
                    if just_cancelled:
                        mcp_result = on_cancel_complete(session.context, settings)
                        st.session_state[MCP_RUN_FOR_KEY] = f"cancel:{session.context.existing_booking_code}"
                        st.session_state[MCP_RESULT_KEY] = mcp_result
                    elif just_confirmed and has_slot:
                        if session.context.intent == "reschedule" and session.context.existing_booking_code:
                            mcp_result = on_reschedule_complete(session.context, settings)
                            st.session_state[MCP_RUN_FOR_KEY] = f"reschedule:{session.context.existing_booking_code}"
                        elif session.context.intent != "reschedule":
                            mcp_result = on_booking_complete(session.context, settings)
                            st.session_state[MCP_RUN_FOR_KEY] = session.context.booking_code or ""
                        else:
                            mcp_result = MCPResult()
                        st.session_state[MCP_RESULT_KEY] = mcp_result
                    for k in ("pending_voice_text", "pending_voice_hash"):
                        if k in st.session_state:
                            del st.session_state[k]
                    st.session_state["voice_recorder_turn"] = st.session_state.get("voice_recorder_turn", 0) + 1
                    # Voice-in → voice-out: show agent reply as text (in chat) and play as TTS on next run
                    st.session_state[AGENT_REPLY_TO_SPEAK_KEY] = turn.text
                st.rerun()
        with col_retry:
            if st.button("Retry", type="secondary", key="voice_confirm_retry"):
                for k in ("pending_voice_text", "pending_voice_hash"):
                    if k in st.session_state:
                        del st.session_state[k]
                st.session_state["voice_recorder_turn"] = st.session_state.get("voice_recorder_turn", 0) + 1
                st.rerun()

    # Voice input: record and transcribe (STT) — skip when pending so we show confirmation only
    # Recorder is always shown so you can reply by voice at any time (scroll down if needed).
    voice_recorder_turn = st.session_state.get("voice_recorder_turn", 0)
    st.markdown("---")
    st.markdown("**Reply by voice or text**")
    voice_audio = st.audio_input("Record your answer (or type below)", key=f"voice_input_{voice_recorder_turn}")
    if voice_audio and not pending_voice_text:
        audio_bytes = voice_audio.read()
        voice_hash = hash(audio_bytes) if audio_bytes else None
        if voice_hash and st.session_state.get(LAST_VOICE_HASH_KEY) != voice_hash:
            with st.spinner("Transcribing..."):
                voice_text = transcribe_audio(audio_bytes) if audio_bytes else None
            if voice_text and voice_text.strip():
                st.session_state[LAST_VOICE_HASH_KEY] = voice_hash
                st.session_state["pending_voice_text"] = voice_text.strip()
                st.session_state["pending_voice_hash"] = voice_hash
                st.rerun()
            elif voice_text is not None:
                st.caption("Could not transcribe. Try typing instead.")
            else:
                st.warning("Transcription failed or was empty. Try recording again (clearer/longer) or type your message below.")

    # Input: form + explicit key so we never touch a widget's session_state key after render
    with st.form("chat_form", clear_on_submit=True):
        msg = st.text_input(
            "Type your message (no phone, email, or account numbers).",
            key="chat_form_text_input",
            placeholder="e.g., I want to book an appointment about SIP mandates",
        )
        submitted = st.form_submit_button("Send")

    if submitted and (msg or "").strip():
        with st.spinner("Agent is processing..."):
            user_text = (msg or "").strip()
            # Append user message first so it always appears in chat (avoids "first yes not captured")
            st.session_state[CHAT_KEY].append(("user", user_text))
            state_before = session.state
            turn: AgentTurn = session.step(user_text)
            st.session_state[CHAT_KEY].append(("agent", turn.text))

            # Phase 2: run MCP when we just completed a booking, reschedule, or cancel
            just_confirmed = (
                state_before == ConversationState.CONFIRMATION
                and turn.state == ConversationState.BOOKING_COMPLETE
            )
            just_cancelled = (
                state_before == ConversationState.CANCEL_CONFIRM
                and turn.state == ConversationState.BOOKING_COMPLETE
                and session.context.existing_booking_code
            )
            has_slot = (
                session.context.chosen_slot_index is not None
                and len(session.context.offered_slots) > session.context.chosen_slot_index
            )
            if just_cancelled:
                mcp_result = on_cancel_complete(session.context, settings)
                st.session_state[MCP_RUN_FOR_KEY] = f"cancel:{session.context.existing_booking_code}"
                st.session_state[MCP_RESULT_KEY] = mcp_result
            elif just_confirmed and has_slot:
                # Reschedule: update existing calendar event and sheet row; never create a new booking.
                if session.context.intent == "reschedule" and session.context.existing_booking_code:
                    mcp_result = on_reschedule_complete(session.context, settings)
                    st.session_state[MCP_RUN_FOR_KEY] = f"reschedule:{session.context.existing_booking_code}"
                elif session.context.intent != "reschedule":
                    # New booking only when intent is book_new (avoid creating duplicate when reschedule intent was lost)
                    mcp_result = on_booking_complete(session.context, settings)
                    st.session_state[MCP_RUN_FOR_KEY] = session.context.booking_code or ""
                else:
                    mcp_result = MCPResult()
                st.session_state[MCP_RESULT_KEY] = mcp_result
        st.rerun()

    # Phase 2 MCP result (when a booking was just completed)
    if MCP_RESULT_KEY in st.session_state:
        mcp_result: MCPResult = st.session_state[MCP_RESULT_KEY]
        with st.expander("Phase 2: Calendar / Sheets", expanded=True):
            st.write("**Calendar:** " + mcp_result.calendar[1])
            st.write("**Sheets:** " + mcp_result.sheets[1])
            if mcp_result.errors:
                st.warning("Some integrations reported errors: " + "; ".join(mcp_result.errors))

    # Debug panel
    with st.expander("Debug: conversation state", expanded=False):
        st.write(
            {
                "state": session.state.name if isinstance(session.state, ConversationState) else str(session.state),
                "intent": session.context.intent,
                "topic": session.context.topic_label,
                "preferred_datetime_text": session.context.preferred_datetime_text,
                "offered_slots": [s.label() for s in session.context.offered_slots],
                "chosen_slot_index": session.context.chosen_slot_index,
                "booking_code": session.context.booking_code,
            }
        )


if __name__ == "__main__":
    main()

