import sqlite3
import json
from datetime import datetime

# Connect to DB
DB_PATH = "projectgpt.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Get user_id for test@test.com
cursor.execute("SELECT id FROM users WHERE email = ?", ("test@test.com",))
row = cursor.fetchone()

if row:
    user_id = row[0]
    title = "The Adventures of AI Bunny"
    field = "Biology"
    topic = "Animal Life"
    grade = "3"

    # 12 pages of dummy story text
    pages = [f"Page {i+1}: This is story content for page {i+1}." for i in range(12)]

    # 12 images pointing to /static/images/a1.png through a12.png
    images = [f"/static/images/a{i+1}.png" for i in range(12)]

    # Insert into user_stories
    cursor.execute("""
        INSERT INTO user_stories (user_id, title, field, topic, grade, story_json, image_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        title,
        field,
        topic,
        grade,
        json.dumps(pages),
        json.dumps(images),
        datetime.now()
    ))

    conn.commit()
    print("✅ Mock storybook added for test@test.com.")
else:
    print("❌ User not found.")
