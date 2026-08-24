from app.models.database import sqlalchemy_database_url


def test_railway_postgres_url_uses_psycopg3_dialect():
    assert sqlalchemy_database_url("postgresql://user:secret@postgres:5432/procura") == (
        "postgresql+psycopg://user:secret@postgres:5432/procura"
    )


def test_sqlite_url_is_unchanged():
    assert sqlalchemy_database_url("sqlite:///./procura.db") == "sqlite:///./procura.db"
