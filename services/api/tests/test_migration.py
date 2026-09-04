from app.models.database import engine, init_db
from sqlalchemy import inspect


def test_additive_schema_initialization_includes_procurement_intakes():
    init_db()
    assert "procurement_intakes" in inspect(engine).get_table_names()
