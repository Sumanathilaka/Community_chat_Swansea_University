import os

from flask import Flask, render_template
from sqlalchemy import inspect, text

from config import Config
from extensions import db, login_manager
from models import User, ChatSession, ChatMessage


def _ensure_schema_up_to_date(app):
    """Lightweight, additive self-migration.

    This project uses db.create_all() instead of a full migration tool
    (Flask-Migrate/Alembic), which only creates *missing* tables — it never
    alters a table that already exists. If a model gains a new column
    (e.g. is_admin) but someone already has an old instance/mino_chat.db
    from before that change, every query touching that table fails with
    'no such column: ...' instead of the app just working.

    This walks each model's expected columns and ALTERs the real table to
    add any that are missing, so upgrading the code doesn't require anyone
    to manually delete their database.
    """
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    for model in (User, ChatSession, ChatMessage):
        table = model.__table__
        if table.name not in existing_tables:
            continue  # a brand-new table is handled fully by create_all()
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_cols:
                continue
            col_type = column.type.compile(dialect=db.engine.dialect)
            default_clause = ""
            if column.default is not None and column.default.is_scalar:
                default_clause = f" DEFAULT {column.default.arg!r}"
            ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}{default_clause}"
            db.session.execute(text(ddl))
            app.logger.warning("Schema upgrade: added missing column %s.%s", table.name, column.name)
    db.session.commit()


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    os.makedirs(os.path.join(app.root_path, "instance"), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import jsonify
        return jsonify(error="Please log in to use this feature."), 401

    from auth import auth_bp
    from chat_api import chat_bp
    from admin import admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        db.create_all()
        _ensure_schema_up_to_date(app)

        # RAG engine is built once and attached to the app; it holds the
        # embedding model, LLM client, and section vectorstores in memory.
        try:
            from rag_engine import RagEngine
            app.rag_engine = RagEngine(app.config)
        except Exception as exc:  # missing credentials / deps during local dev
            app.logger.warning("RAG engine failed to initialise: %s", exc)
            app.rag_engine = None

    @app.get("/")
    def index():
        return render_template("chat.html")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
