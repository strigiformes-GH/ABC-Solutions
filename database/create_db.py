# prepare the db and connect it to the app


from __future__ import annotations  # flexible type hints
from pathlib import Path
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine  # engine class import


db = SQLAlchemy(session_options={"expire_on_commit": False})


@event.listens_for(Engine, "connect")
def enable_sqlite_fks(dbapi_connection, _connection_record) -> None:
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")  # enforce fk rules
        cursor.close()


def create_db(app):
    uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    # db address missing
    if not uri:
        raise ValueError("Set SQLALCHEMY_DATABASE_URI in config.")
    # file-based db
    if uri.startswith("sqlite:///") and uri != "sqlite:///:memory:":
        db_path = uri.removeprefix("sqlite:///")
        path = Path(db_path)
        # relative paths pointed into flask folder
        if not path.is_absolute():
            path = Path(app.root_path) / path
        # create folder if it doesn't exist
        path.parent.mkdir(parents=True, exist_ok=True)
        # save to config
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{path}"
        # let connections work across different threads
        options = app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {})
        options.setdefault("connect_args", {"check_same_thread": False})
    db.init_app(app)