import os
from functools import wraps

from flask import Blueprint, request, jsonify, render_template, redirect, url_for, current_app
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

admin_bp = Blueprint("admin", __name__)


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify(error="Please log in."), 401
        if not current_user.is_admin:
            return jsonify(error="Admin access required."), 403
        return view_func(*args, **kwargs)
    return wrapper


def _data_path():
    return current_app.config["DATA_PATH"]


def _safe_section_name(name: str) -> str:
    """Turn a user-supplied folder name into something filesystem-safe and
    prevent path traversal (no '..', slashes, etc.)."""
    name = secure_filename((name or "").strip())
    return name


# ── Page route ───────────────────────────────────────────────────────────
@admin_bp.get("/admin")
@login_required
def admin_page():
    if not current_user.is_admin:
        return redirect(url_for("index"))
    return render_template("admin.html")


# ── API routes ───────────────────────────────────────────────────────────
@admin_bp.get("/api/admin/sections")
@admin_required
def list_sections():
    data_path = _data_path()
    sections = []
    if os.path.isdir(data_path):
        for name in sorted(os.listdir(data_path)):
            folder = os.path.join(data_path, name)
            if not os.path.isdir(folder):
                continue
            pdf_count = len([f for f in os.listdir(folder) if f.lower().endswith(".pdf")])
            sections.append({"name": name, "pdf_count": pdf_count})
    return jsonify(sections=sections)


@admin_bp.get("/api/admin/pdfs")
@admin_required
def list_pdfs():
    section = _safe_section_name(request.args.get("section", ""))
    if not section:
        return jsonify(error="A section name is required."), 400
    folder = os.path.join(_data_path(), section)
    if not os.path.isdir(folder):
        return jsonify(files=[])
    files = []
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith(".pdf"):
            path = os.path.join(folder, name)
            files.append({"name": name, "size_kb": round(os.path.getsize(path) / 1024, 1)})
    return jsonify(files=files)


@admin_bp.post("/api/admin/upload")
@admin_required
def upload_pdfs():
    section = _safe_section_name(request.form.get("section", ""))
    new_section = _safe_section_name(request.form.get("new_section", ""))
    section = new_section or section

    if not section:
        return jsonify(error="Choose an existing folder or name a new one."), 400

    files = request.files.getlist("files")
    pdfs = [f for f in files if f and f.filename.lower().endswith(".pdf")]
    if not pdfs:
        return jsonify(error="Attach at least one PDF file."), 400

    folder = os.path.join(_data_path(), section)
    os.makedirs(folder, exist_ok=True)

    saved = []
    skipped = []
    for f in pdfs:
        safe_name = secure_filename(f.filename)
        if not safe_name:
            continue
        dest = os.path.join(folder, safe_name)
        if os.path.exists(dest):
            skipped.append(safe_name)
            continue
        f.save(dest)
        saved.append(safe_name)

    return jsonify(ok=True, section=section, saved=saved, skipped=skipped)


@admin_bp.delete("/api/admin/pdfs")
@admin_required
def delete_pdf():
    data = request.get_json(silent=True) or {}
    section = _safe_section_name(data.get("section", ""))
    filename = secure_filename(data.get("filename", ""))
    if not section or not filename:
        return jsonify(error="Section and filename are required."), 400

    path = os.path.join(_data_path(), section, filename)
    if not os.path.isfile(path):
        return jsonify(error="File not found."), 404

    os.remove(path)
    return jsonify(ok=True)


@admin_bp.post("/api/admin/rebuild_index")
@admin_required
def rebuild_index():
    engine = current_app.rag_engine
    if engine is None:
        return jsonify(error="RAG engine is not initialised (check dependencies/credentials)."), 500
    sections = engine.load_base_sections(force_rebuild=True)
    return jsonify(ok=True, sections=list(sections.keys()))
