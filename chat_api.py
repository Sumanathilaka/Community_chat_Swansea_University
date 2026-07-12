import os
import json
import uuid

from flask import Blueprint, request, jsonify, session, current_app
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from extensions import db
from models import ChatSession, ChatMessage

chat_bp = Blueprint("chat", __name__, url_prefix="/api")

# runtime_session_id -> {"chat_pairs": [...], "db_session_id": int|None, "attached_names": [...]}
# In-memory, same lifetime tradeoff as the original Streamlit `store = {}`.
RUNTIME_CHATS = {}


def _get_rsid() -> str:
    """Every browser gets a runtime session id (independent of login), so
    guests can chat without ever creating an account."""
    rsid = session.get("rsid")
    if not rsid:
        rsid = uuid.uuid4().hex
        session["rsid"] = rsid
    if rsid not in RUNTIME_CHATS:
        RUNTIME_CHATS[rsid] = {"chat_pairs": [], "db_session_id": None, "attached_names": []}
    return rsid


def _engine():
    return current_app.rag_engine


@chat_bp.get("/state")
def state():
    """Initial state the frontend needs on page load: current draft chat,
    whether it's already saved, and (if logged in) the saved-chat sidebar list."""
    rsid = _get_rsid()
    entry = RUNTIME_CHATS[rsid]
    saved_sessions = []
    if current_user.is_authenticated:
        saved_sessions = [
            s.to_dict()
            for s in ChatSession.query.filter_by(user_id=current_user.id)
            .order_by(ChatSession.updated_at.desc())
            .all()
        ]
    return jsonify(
        user=current_user.to_dict() if current_user.is_authenticated else None,
        chat_pairs=entry["chat_pairs"],
        attached_names=entry["attached_names"],
        is_saved=entry["db_session_id"] is not None,
        saved_sessions=saved_sessions,
        sections=list(_engine().section_stores.keys()) if _engine() else [],
    )


@chat_bp.post("/chat")
def chat():
    rsid = _get_rsid()
    entry = RUNTIME_CHATS[rsid]

    message = (request.form.get("message") or (request.get_json(silent=True) or {}).get("message") or "").strip()
    files = request.files.getlist("files") if request.files else []

    if not message and not files:
        return jsonify(error="Please enter a message."), 400

    engine = _engine()

    # Index any newly attached PDFs into this session's private UPLOAD store
    if files:
        os.makedirs(current_app.config["UPLOAD_TMP_DIR"], exist_ok=True)
        saved_paths = []
        new_names = []
        for f in files:
            if not f.filename.lower().endswith(".pdf"):
                continue
            safe_name = secure_filename(f.filename)
            dest = os.path.join(current_app.config["UPLOAD_TMP_DIR"], f"{rsid}_{safe_name}")
            f.save(dest)
            saved_paths.append(dest)
            new_names.append(f.filename)
        if saved_paths:
            engine.build_upload_store_for_session(rsid, saved_paths)
            entry["attached_names"].extend(n for n in new_names if n not in entry["attached_names"])

    if not message:
        return jsonify(
            answer=None,
            attached_names=entry["attached_names"],
            note="Files indexed. Ask a question about them whenever you're ready.",
        )

    # ── Tool selections from the composer's "Select Tools" picker ───────
    tools_raw = request.form.get("tools")
    tools = {}
    if tools_raw:
        try:
            tools = json.loads(tools_raw)
        except (TypeError, ValueError):
            tools = {}
    selected_stores = [s for s in (tools.get("vector_stores") or []) if isinstance(s, str)]
    use_hate_speech = bool(tools.get("hate_speech"))
    tools_requested = bool(selected_stores) or use_hate_speech

    if engine is None:
        result = {"answer": None, "searched": [], "references": [], "moderation": None}
        answer_text = "The assistant isn't available right now (RAG engine failed to start)."
    elif not engine.has_knowledge(rsid) and not tools_requested:
        result = {"answer": None, "searched": [], "references": [], "moderation": None}
        answer_text = "No knowledge base is available yet. Attach a PDF or ask a general question."
    else:
        result = engine.ask(rsid, message, selected_stores=selected_stores, use_hate_speech=use_hate_speech)
        answer_text = result["answer"]

    pair = {
        "user": message,
        "assistant": answer_text,
        "searched": result.get("searched", []),
        "references": result.get("references", []),
        "moderation": result.get("moderation"),
    }
    entry["chat_pairs"].append(pair)

    # If this conversation is already saved, keep the DB copy in sync automatically.
    if entry["db_session_id"] and current_user.is_authenticated:
        chat_session = ChatSession.query.get(entry["db_session_id"])
        if chat_session and chat_session.user_id == current_user.id:
            extra_json = json.dumps({"references": pair["references"], "moderation": pair["moderation"]})
            db.session.add(ChatMessage(session_id=chat_session.id, role="user", content=message))
            db.session.add(ChatMessage(
                session_id=chat_session.id, role="assistant", content=answer_text,
                searched_sections=",".join(pair["searched"]), extra_json=extra_json,
            ))
            db.session.commit()

    return jsonify(
        answer=answer_text,
        searched=pair["searched"],
        references=pair["references"],
        moderation=pair["moderation"],
        attached_names=entry["attached_names"],
        is_saved=entry["db_session_id"] is not None,
    )


@chat_bp.post("/new_chat")
def new_chat():
    old_rsid = session.get("rsid")
    if old_rsid:
        engine = _engine()
        if engine:
            engine.reset_session_history(old_rsid)
            engine.clear_upload_store(old_rsid)
        RUNTIME_CHATS.pop(old_rsid, None)

    new_rsid = uuid.uuid4().hex
    session["rsid"] = new_rsid
    RUNTIME_CHATS[new_rsid] = {"chat_pairs": [], "db_session_id": None, "attached_names": []}
    return jsonify(ok=True)


@chat_bp.post("/save_chat")
@login_required
def save_chat():
    rsid = _get_rsid()
    entry = RUNTIME_CHATS[rsid]

    if not entry["chat_pairs"]:
        return jsonify(error="Nothing to save yet — send a message first."), 400

    if entry["db_session_id"]:
        chat_session = ChatSession.query.get(entry["db_session_id"])
        return jsonify(ok=True, session=chat_session.to_dict(), already_saved=True)

    title = entry["chat_pairs"][0]["user"][:60] or "New Chat"
    chat_session = ChatSession(user_id=current_user.id, title=title)
    db.session.add(chat_session)
    db.session.flush()  # get chat_session.id

    for pair in entry["chat_pairs"]:
        extra_json = json.dumps({
            "references": pair.get("references", []),
            "moderation": pair.get("moderation"),
        })
        db.session.add(ChatMessage(session_id=chat_session.id, role="user", content=pair["user"]))
        db.session.add(ChatMessage(
            session_id=chat_session.id, role="assistant", content=pair["assistant"] or "",
            searched_sections=",".join(pair.get("searched", [])), extra_json=extra_json,
        ))
    db.session.commit()

    entry["db_session_id"] = chat_session.id
    return jsonify(ok=True, session=chat_session.to_dict())


@chat_bp.get("/sessions")
@login_required
def list_sessions():
    sessions = (
        ChatSession.query.filter_by(user_id=current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return jsonify(sessions=[s.to_dict() for s in sessions])


@chat_bp.get("/sessions/<int:session_id>")
@login_required
def load_session(session_id):
    chat_session = ChatSession.query.get_or_404(session_id)
    if chat_session.user_id != current_user.id:
        return jsonify(error="Not found."), 404

    messages = [m.to_dict() for m in chat_session.messages]
    chat_pairs = []
    pending_user = None
    for m in messages:
        if m["role"] == "user":
            pending_user = m["content"]
        else:
            chat_pairs.append({
                "user": pending_user or "", "assistant": m["content"], "searched": m["searched"],
                "references": m.get("references", []), "moderation": m.get("moderation"),
            })
            pending_user = None

    # Start a fresh runtime slot bound to this saved session so new messages append to it.
    old_rsid = session.get("rsid")
    if old_rsid:
        engine = _engine()
        if engine:
            engine.clear_upload_store(old_rsid)
        RUNTIME_CHATS.pop(old_rsid, None)

    new_rsid = uuid.uuid4().hex
    session["rsid"] = new_rsid
    RUNTIME_CHATS[new_rsid] = {
        "chat_pairs": chat_pairs, "db_session_id": chat_session.id, "attached_names": [],
    }
    flat_messages = [{"role": m["role"], "content": m["content"]} for m in messages]
    engine = _engine()
    if engine:
        engine.seed_session_history(new_rsid, flat_messages)

    return jsonify(session=chat_session.to_dict(), chat_pairs=chat_pairs)


@chat_bp.delete("/sessions/<int:session_id>")
@login_required
def delete_session(session_id):
    chat_session = ChatSession.query.get_or_404(session_id)
    if chat_session.user_id != current_user.id:
        return jsonify(error="Not found."), 404

    rsid = session.get("rsid")
    if rsid and RUNTIME_CHATS.get(rsid, {}).get("db_session_id") == session_id:
        RUNTIME_CHATS[rsid]["db_session_id"] = None

    db.session.delete(chat_session)
    db.session.commit()
    return jsonify(ok=True)



