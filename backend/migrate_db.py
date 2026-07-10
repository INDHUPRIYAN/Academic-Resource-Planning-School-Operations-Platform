import sqlite3
import os

def migrate():
    db_path = "test.db"
    if not os.path.exists(db_path):
        print(f"Database file '{db_path}' does not exist yet. Run metadata creation.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Check teachers columns
    cursor.execute("PRAGMA table_info(teachers)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if "teaching_group_id" not in columns:
        print("Adding teaching_group_id to teachers table...")
        try:
            cursor.execute("ALTER TABLE teachers ADD COLUMN teaching_group_id INTEGER REFERENCES teaching_groups(id)")
            conn.commit()
            print("Successfully added teaching_group_id.")
        except Exception as e:
            print(f"Error adding teaching_group_id: {e}")
    else:
        print("teaching_group_id already exists in teachers table.")

    # Check subject_assignments columns
    cursor.execute("PRAGMA table_info(subject_assignments)")
    sa_columns = [col[1] for col in cursor.fetchall()]
    if "weekly_hours_override" not in sa_columns:
        print("Adding weekly_hours_override to subject_assignments table...")
        try:
            cursor.execute("ALTER TABLE subject_assignments ADD COLUMN weekly_hours_override INTEGER")
            conn.commit()
            print("Successfully added weekly_hours_override.")
        except Exception as e:
            print(f"Error adding weekly_hours_override: {e}")

    conn.close()

if __name__ == "__main__":
    migrate()
