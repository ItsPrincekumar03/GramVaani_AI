"""Upgraded File Complaint page - voice + manual complaint filing."""

import html
import traceback
from datetime import date
from pathlib import Path
from typing import Optional

import streamlit as st

from ai.llm.complaint_generator import generate_complaint
from ai.schemes.scheme_recommender import recommend_schemes
from ai.speech.speech_service import transcribe_audio
from ai.speech.speech_utils import delete_temp_file, save_uploaded_audio
from ai.utils.complaint_id import generate_complaint_id
from ai.utils.complaint_tracker import SESSION_STATE_REGISTRY_KEY as TRACKER_REGISTRY_KEY
from ai.utils.complaint_tracker import register_complaint
from ai.utils.pdf_generator import generate_complaint_pdf
from frontend.components.evidence_uploader import (
    EVIDENCE_STATE_KEY,
    delete_evidence_image,
    render_evidence_upload_section,
)
from frontend.components.theme import (
    department_badge_html,
    page_header,
    priority_badge_html,
)
from frontend.config.constants import (
    AUDIO_SUPPORTED_FORMATS,
    LANGUAGE_CODE_MAP,
    LANGUAGE_OPTIONS,
)
from frontend.utils.i18n import t

_TRANSCRIPT_STATE_KEY: str = "gv_recognized_speech"
_COMPLAINT_STATE_KEY: str = "gv_generated_complaint"
_MANUAL_DRAFT_KEY: str = "gv_manual_draft"
SCHEMES_STATE_KEY: str = "gv_recommended_schemes"


def _handle_process_audio(uploaded_file, language_code: Optional[str]) -> None:
    if uploaded_file is None:
        st.warning(t("file_complaint.audio_no_file_warning"))
        return
    if uploaded_file.size == 0:
        st.warning(t("file_complaint.audio_empty_file_warning"))
        return
    temp_audio_path: Optional[Path] = None
    with st.spinner(t("file_complaint.audio_processing_message")):
        try:
            temp_audio_path = save_uploaded_audio(uploaded_file)
            transcript = transcribe_audio(temp_audio_path, language=language_code)
        except ValueError:
            st.error(t("file_complaint.audio_unsupported_format_error"))
            return
        except (FileNotFoundError, RuntimeError):
            st.error(t("file_complaint.audio_transcription_failed_error"))
            return
        finally:
            delete_temp_file(temp_audio_path)
    if not transcript:
        st.warning(t("file_complaint.audio_no_speech_detected_warning"))
        st.session_state.pop(_TRANSCRIPT_STATE_KEY, None)
        return
    st.session_state[_TRANSCRIPT_STATE_KEY] = transcript
    st.session_state.pop(_COMPLAINT_STATE_KEY, None)
    st.session_state.pop(SCHEMES_STATE_KEY, None)


def _finalize_complaint(complaint: dict) -> None:
    complaint["complaint_id"] = generate_complaint_id()
    complaint["generated_date"] = date.today().strftime("%d %B %Y")
    st.session_state[_COMPLAINT_STATE_KEY] = complaint
    try:
        tracking_registry = st.session_state.setdefault(TRACKER_REGISTRY_KEY, {})
        register_complaint(tracking_registry, complaint)
    except Exception:  # noqa: BLE001
        print(traceback.format_exc())
    try:
        schemes = recommend_schemes(
            complaint_type=complaint.get("complaint_type", ""),
            department=complaint.get("department", ""),
            summary=complaint.get("summary", ""),
        )
    except Exception:  # noqa: BLE001
        print(traceback.format_exc())
        schemes = t("file_complaint.scheme_no_match_message")
    st.session_state[SCHEMES_STATE_KEY] = schemes


def _handle_generate_complaint(transcript: Optional[str]) -> None:
    if not transcript or not transcript.strip():
        st.warning(t("file_complaint.empty_transcript_warning"))
        return
    with st.spinner(t("file_complaint.generation_processing_message")):
        try:
            complaint = generate_complaint(transcript)
        except ValueError:
            st.warning(t("file_complaint.empty_transcript_warning"))
            return
        except Exception as exc:
            print(traceback.format_exc())
            st.exception(exc)
            return
    _finalize_complaint(complaint)


def _handle_manual_generate(draft: str) -> None:
    if not draft or not draft.strip():
        st.warning(t("file_complaint.empty_transcript_warning"))
        return
    with st.spinner(t("file_complaint.generation_processing_message")):
        try:
            complaint = generate_complaint(draft)
        except ValueError:
            st.warning(t("file_complaint.empty_transcript_warning"))
            return
        except Exception as exc:
            print(traceback.format_exc())
            st.exception(exc)
            return
    _finalize_complaint(complaint)


def _render_transcript_if_available() -> None:
    transcript = st.session_state.get(_TRANSCRIPT_STATE_KEY)
    if not transcript:
        return
    safe_transcript = html.escape(transcript)
    st.write("")
    st.markdown(
        f"""<div class="gv-card"><h3>{t("file_complaint.transcript_card_title")}</h3><p>{safe_transcript}</p></div>""",
        unsafe_allow_html=True,
    )
    st.write("")
    transcript = st.text_area(
        t("file_complaint.transcript_card_title"),
        value=transcript,
        key="gv_transcript_editor",
    )
    st.session_state[_TRANSCRIPT_STATE_KEY] = transcript
    if st.button(
        t("file_complaint.generate_complaint_button_label"),
        use_container_width=True,
        type="primary",
        key="gv_generate_complaint_button",
    ):
        _handle_generate_complaint(transcript)


def _render_complaint_result_if_available() -> None:
    complaint = st.session_state.get(_COMPLAINT_STATE_KEY)
    if not complaint:
        return
    complaint_id = html.escape(str(complaint.get("complaint_id", "")))
    complaint_type = html.escape(str(complaint.get("complaint_type", "")))
    department_badge = department_badge_html(complaint.get("department", ""))
    priority_badge = priority_badge_html(complaint.get("priority", ""))
    summary = html.escape(str(complaint.get("summary", "")))
    formal_complaint = html.escape(str(complaint.get("formal_complaint", "")))
    evidence = st.session_state.get(EVIDENCE_STATE_KEY)
    evidence_row = ""
    if evidence:
        evidence_filename = html.escape(str(evidence.get("filename", "")))
        evidence_row = f'<p>{t("file_complaint.evidence_attached_note")} <strong>{evidence_filename}</strong></p>'
    st.write("")
    st.markdown(
        f"""<div class="gv-card">
            <h3>{t("file_complaint.result_card_title")}</h3>
            <p><strong>{t("file_complaint.complaint_id_label")}:</strong> {complaint_id}</p>
            <p><strong>{t("file_complaint.complaint_type_label")}:</strong> {complaint_type}</p>
            <p><strong>{t("file_complaint.department_label")}:</strong> {department_badge}</p>
            <p><strong>{t("file_complaint.priority_label")}:</strong> {priority_badge}</p>
            <p><strong>{t("file_complaint.summary_label")}:</strong> {summary}</p>
            <p><strong>{t("file_complaint.formal_text_label")}:</strong><br>{formal_complaint}</p>
            {evidence_row}
        </div>""",
        unsafe_allow_html=True,
    )
    st.caption(t("file_complaint.complaint_id_copy_caption"))
    st.code(str(complaint.get("complaint_id", "")), language=None)


def _handle_pdf_downloaded() -> None:
    if not st.session_state.get("gv_auto_delete_files", True):
        return
    evidence = st.session_state.get(EVIDENCE_STATE_KEY)
    if not evidence:
        return
    delete_evidence_image(evidence.get("path"))
    st.session_state[EVIDENCE_STATE_KEY] = None
    st.session_state.pop("gv_evidence_uploader", None)


def _render_download_button_if_available() -> None:
    complaint = st.session_state.get(_COMPLAINT_STATE_KEY)
    if not complaint:
        return
    schemes = st.session_state.get(SCHEMES_STATE_KEY)
    evidence = st.session_state.get(EVIDENCE_STATE_KEY)
    evidence_image_path = evidence.get("path") if evidence else None
    evidence_filename = evidence.get("filename") if evidence else None
    try:
        pdf_bytes = generate_complaint_pdf(
            complaint, schemes,
            evidence_image_path=evidence_image_path,
            evidence_filename=evidence_filename,
        )
    except Exception:  # noqa: BLE001
        print(traceback.format_exc())
        st.error(t("file_complaint.pdf_generation_failed_error"))
        return
    complaint_id = str(complaint.get("complaint_id", "")).strip()
    file_name = f"{complaint_id}.pdf" if complaint_id else "gramvaani_complaint.pdf"
    st.write("")
    st.download_button(
        label=t("file_complaint.download_button_label"),
        data=pdf_bytes,
        file_name=file_name,
        mime="application/pdf",
        use_container_width=True,
        type="primary",
        on_click=_handle_pdf_downloaded,
        key="gv_download_complaint_pdf",
    )


def render() -> None:
    page_header(
        title=t("file_complaint.title"),
        subtitle=t("file_complaint.subtitle"),
        eyebrow=t("file_complaint.eyebrow"),
    )

    tab_voice, tab_manual = st.tabs(["🎤 Voice Complaint", "✍️ Written Complaint"])

    with tab_voice:
        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown(
                f"""<div class="gv-card"><h3>{t("file_complaint.voice_card_title")}</h3><p>{t("file_complaint.voice_card_text")}</p></div>""",
                unsafe_allow_html=True,
            )
            st.write("")
            language_option_labels = t("file_complaint.language_option_labels")
            selected_language_label = st.radio(
                label=t("file_complaint.language_label"),
                options=LANGUAGE_OPTIONS,
                format_func=lambda option: language_option_labels.get(option, option),
                horizontal=True,
                key="gv_complaint_language",
            )
            uploaded_audio = st.file_uploader(
                label=t("file_complaint.audio_uploader_label"),
                type=AUDIO_SUPPORTED_FORMATS,
                help=t("file_complaint.audio_uploader_help"),
                key="gv_audio_uploader",
            )
            if st.button(
                t("file_complaint.process_audio_button_label"),
                use_container_width=True,
                type="primary",
                key="gv_process_audio_button",
            ):
                language_code = LANGUAGE_CODE_MAP[selected_language_label]
                _handle_process_audio(uploaded_audio, language_code)
        with col_right:
            st.markdown(
                f"""<div class="gv-card"><h3>{t("file_complaint.image_card_title")}</h3><p>{t("file_complaint.image_card_text")}</p></div>""",
                unsafe_allow_html=True,
            )
            st.write("")
            render_evidence_upload_section()

    with tab_manual:
        st.markdown("### Manual Written Complaint")
        title = st.text_input("Complaint Title")
        desc = st.text_area("Detailed Complaint Description", height=150)
        category = st.selectbox("Complaint Category", ["General", "Water", "Electricity", "Road", "Sanitation", "Other"])
        department = st.selectbox("Relevant Department", ["Municipal", "PWD", "Electricity Board", "Water Board", "Other"])
        incident_date = st.date_input("Incident Date")
        location = st.text_input("Incident Location")
        state = st.text_input("State")
        district = st.text_input("District")
        city = st.text_input("City / Village")
        address = st.text_area("Full Address")
        citizen_name = st.text_input("Citizen Name")
        mobile = st.text_input("Mobile Number")
        email = st.text_input("Email Address")
        priority = st.selectbox("Priority", ["Low", "Medium", "High"])
        if st.button("Generate from Written Complaint", use_container_width=True, type="primary"):
            draft = f"Title: {title}\nDescription: {desc}\nCategory: {category}\nDepartment: {department}\nDate: {incident_date}\nLocation: {location}, {city}, {district}, {state}\nAddress: {address}\nCitizen: {citizen_name}, {mobile}, {email}\nPriority: {priority}"
            st.session_state[_MANUAL_DRAFT_KEY] = draft
            _handle_manual_generate(draft)
        draft = st.session_state.get(_MANUAL_DRAFT_KEY)
        if draft:
            st.text_area("AI-reviewed draft (editable)", value=draft, key="gv_manual_draft_editor")

    _render_transcript_if_available()
    _render_complaint_result_if_available()

    complaint = st.session_state.get(_COMPLAINT_STATE_KEY)
    if complaint:
        if not st.session_state.get("gv_complaint_confirmed", False):
            confirmed = st.checkbox("I confirm all details above are correct", key="gv_confirm_checkbox")
            if confirmed and st.button("Confirm and Finalize Complaint", use_container_width=True, type="primary", key="gv_confirm_finalize"):
                st.session_state["gv_complaint_confirmed"] = True
                st.session_state["gv_complaint_submitted_id"] = complaint.get("complaint_id")
                st.rerun()
        else:
            st.success("Complaint filed. Reference ID: " + str(complaint.get("complaint_id")))
            _render_download_button_if_available()