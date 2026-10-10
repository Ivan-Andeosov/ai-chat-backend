from sqlalchemy import inspect

from database import DATABASE_URL, engine, init_db

if __name__ == "__main__":
    init_db()

    print(f"Database: {DATABASE_URL}\n")
    inspector = inspect(engine)
    for table in inspector.get_table_names():
        print(table)
        for column in inspector.get_columns(table):
            print(f"    {column['name']}: {column['type']}")
