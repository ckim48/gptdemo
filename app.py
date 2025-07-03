import uuid
import json
import os
import requests
from flask import Flask, render_template, request, send_file, session, redirect, url_for, flash
from elevenlabs import ElevenLabs
from openai import OpenAI
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from io import BytesIO
from datetime import datetime, date
import random
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from generate_tts import generate_storybook_audio
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

app.secret_key = "secret_key_here"
STORY_JSON_PATH = "saved_data/story.json"
IMAGES_JSON_PATH = "saved_data/images.json"
IMAGE_DIR = "static/images"
DB_PATH = "projectgpt.db"



os.makedirs("saved_data", exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)


import json.decoder  # at the top if not already imported

available_voices = {
    "Narrator": 'pMsXgVXv3BLzUgSXRplE',
    "Young girl": 'z9fAnlkpzviPz146aGWa',
    "Funny girl": 'jsCqWAovK2LkecY7zXl4',
    "Deep Male": 'onwK4e9ZLuTAKqWW03F9',
    "Playful Boy": 'D38z5RcWu1voky8WS1ja',
    "Monster": 'JBFqnCBsd6RMkjVDRZzb',
}

# projectGpt.com/generate_audio

import re
import json
from datetime import date

import re

def extract_first_json(text):
    """Extract the first complete JSON object from a string."""
    json_pattern = re.compile(r'\{.*?\}', re.DOTALL)
    matches = json_pattern.findall(text)
    for m in matches:
        try:
            return json.loads(m)
        except json.JSONDecodeError:
            continue
    raise ValueError("No valid JSON found in GPT output.")
@app.route("/generate_quiz/<int:story_id>", methods=["POST"])
def generate_quiz(story_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    # Step 0: Check if quiz already exists
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) FROM user_story_quiz WHERE user_id = ? AND story_id = ?
        """, (user_id, story_id))
        count = c.fetchone()[0]
        if count > 0:
            flash("Quiz already generated for this story.", "info")
            return redirect(url_for("view_quiz", story_id=story_id))

    try:
        # Step 1: Fetch story content
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT story_json FROM user_stories WHERE id = ?", (story_id,))
        row = c.fetchone()
        conn.close()

        if not row:
            flash("Story not found.", "danger")
            return redirect(url_for("profile"))

        story_content = row[0]

        # Step 2: Generate quiz using GPT
        prompt = f"""
        Generate 10 multiple choice quiz questions based on the following children's story:

        \"\"\"{story_content}\"\"\"

        Format:
        [
          {{
            "question": "...",
            "options": {{
              "A": "...",
              "B": "...",
              "C": "...",
              "D": "..."
            }},
            "answer": "A"
          }},
          ...
        ]

        Only return valid JSON.
        """

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}]
        )
        quiz_text = response.choices[0].message.content.strip()

        try:
            questions = json.loads(quiz_text)
        except json.JSONDecodeError:
            try:
                from ast import literal_eval
                questions = literal_eval(quiz_text)
            except Exception as e:
                print("Fallback parse failed:", e)
                flash("Quiz formatting error. Try regenerating.", "danger")
                return redirect(url_for("profile"))

        # Step 3: Save quiz into DB
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        for q in questions:
            c.execute("""
                INSERT INTO user_story_quiz (user_id, story_id, question, options, correct_answer)
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                story_id,
                q["question"],
                json.dumps(q["options"]),
                q["answer"]
            ))
        conn.commit()
        conn.close()

        flash("Quiz generated successfully.", "success")
        return redirect(url_for("view_quiz", story_id=story_id))

    except Exception as e:
        print("Quiz generation error:", e)
        flash("Failed to generate quiz.", "danger")
        return redirect(url_for("profile"))


@app.route("/quiz/<int:story_id>", methods=["GET", "POST"])
def view_quiz(story_id):
    user_id = session.get("user_id")
    if not user_id:
        flash("Please log in to view the quiz.", "warning")
        return redirect(url_for("login"))

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        cursor.execute("""
            SELECT question, options, correct_answer, selected_answer, is_correct 
            FROM user_story_quiz 
            WHERE user_id = ? AND story_id = ?
        """, (user_id, story_id))
        rows = cursor.fetchall()

        if not rows:
            flash("Quiz not available. Please generate it first.", "info")
            return redirect(url_for("profile"))

        # Parse multiple questions
        questions = []
        options = []
        selected = []
        correct = []

        for row in rows:
            questions.append(row[0])
            options.append(json.loads(row[1]))
            correct.append(row[2])
            selected.append(row[3] if row[3] else None)

        return render_template(
            "quiz_detail.html",
            question=questions,
            options=options,
            selected=selected,
            correct=correct
        )


@app.route("/daily_quiz", methods=["GET", "POST"])
def daily_quiz():
    if "user_id" not in session:
        flash("Please log in to take your daily quiz.", "warning")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    today = date.today().isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        # Fetch existing quiz
        cursor.execute(
            "SELECT question, options, correct_answer, selected_answer, is_correct "
            "FROM user_daily_quiz WHERE user_id = ? AND quiz_date = ?",
            (user_id, today)
        )
        row = cursor.fetchone()

        if request.method == "POST" and row:
            try:
                user_answers = [request.form.get(f"q{i}") for i in range(10)]
                correct_answers = json.loads(row[2])
                results = [ua == ca for ua, ca in zip(user_answers, correct_answers)]
                correct_count = sum(results)

                cursor.execute("""
                    UPDATE user_daily_quiz
                    SET selected_answer = ?, is_correct = ?
                    WHERE user_id = ? AND quiz_date = ?
                """, (json.dumps(user_answers), correct_count, user_id, today))
                conn.commit()

                flash(f"You got {correct_count}/10 correct!", "info")
                return redirect(url_for("daily_quiz"))
            except Exception as e:
                print("Error processing submission:", e)
                flash("Error submitting answers.", "danger")
                return redirect(url_for("daily_quiz"))

        if row:
            try:
                question = json.loads(row[0])
                options = json.loads(row[1])
                correct = json.loads(row[2])
                selected = json.loads(row[3]) if row[3] else []
                return render_template("daily_quiz.html",
                                       question=question,
                                       options=options,
                                       answered=bool(row[3]),
                                       selected=selected,
                                       correct=correct)
            except Exception as e:
                print("Error parsing stored quiz JSON:", e)
                # Continue to regenerate below

        # Get latest story to base quiz on
        cursor.execute(
            "SELECT story_json FROM user_stories WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,))
        latest = cursor.fetchone()

        if not latest:
            flash("Please generate a storybook before taking quizzes.", "info")
            return redirect(url_for("generate"))

        pages = json.loads(latest[0])
        context = " ".join(pages)

        # Generate quiz from story
        prompt = f"""
        Generate 10 multiple choice quiz questions based on the following children's story:

        \"\"\"{context}\"\"\"

        Format:
        [
          {{
            "question": "...",
            "options": {{
              "A": "...",
              "B": "...",
              "C": "...",
              "D": "..."
            }},
            "answer": "A"
          }},
          ...
        ]

        Only return valid JSON.
        """

        try:
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1200
            )
            content = response.choices[0].message.content.strip()
            quiz_data = json.loads(content)

            if not isinstance(quiz_data, list) or len(quiz_data) != 10:
                raise ValueError("Invalid quiz data structure")

            questions = [q["question"] for q in quiz_data]
            options = [q["options"] for q in quiz_data]
            answers = [q["answer"] for q in quiz_data]

            cursor.execute("""
                INSERT INTO user_daily_quiz (user_id, quiz_date, question, options, correct_answer)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, today, json.dumps(questions), json.dumps(options), json.dumps(answers)))
            conn.commit()

            return render_template("daily_quiz.html",
                                   question=questions,
                                   options=options,
                                   answered=False,
                                   correct=answers)

        except Exception as e:
            print("GPT quiz generation error:", e)
            flash("Unable to generate quiz today. Try again later.", "danger")
            return redirect(url_for("index"))


@app.route('/generate_audio', methods=["GET","POST"])
def generate_audio():
    try:
        with open("saved_data/story.json") as f:
            pages = json.load(f)
        title = pages[0].split("\n")[0] if pages else "Unavailable"

        audio_path = generate_storybook_audio(pages, title)
        return send_file('storybook.mp3', as_attachment=True,download_name = "storybook_audio.mp3")
    except Exception as e:
        return f"Audio generation failed: {e}"

@app.route("/download_pdf/<int:story_id>")
def download_pdf(story_id):
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("login"))

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT story_json, image_json FROM user_stories WHERE id = ? AND user_id = ?", (story_id, user_id))
    row = cursor.fetchone()

    if not row:
        return "Story not found or access denied", 403

    pages = json.loads(row[0])
    images = json.loads(row[1])

    # (re-use your PDF generation logic)
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(letter))

    width, height = landscape(letter)
    padding = 50
    gutter = 30
    text_box_x = padding
    text_box_y = height - padding
    text_box_width = (width - 2 * padding - gutter) * 0.5
    text_box_height = height - 2 * padding
    image_box_x = text_box_x + text_box_width + gutter
    image_box_y = padding
    image_box_width = text_box_width
    image_box_height = text_box_height

    for i, (text, img_path) in enumerate(zip(pages, images)):
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(padding, height - 30, f"Page {i + 1}")
        pdf.setFont("Times-Roman", 14)
        text_obj = pdf.beginText(text_box_x, text_box_y - 40)
        text_obj.setLeading(22)
        for line in split_text(text, 80):
            if text_obj.getY() < padding:
                break
            text_obj.textLine(line)
        pdf.drawText(text_obj)

        if img_path:
            try:
                image_reader = ImageReader("." + img_path)
                pdf.drawImage(image_reader, image_box_x, image_box_y,
                              width=image_box_width, height=image_box_height,
                              preserveAspectRatio=True, anchor='c')
            except Exception as e:
                print(f"Image load error: {e}")

        pdf.showPage()

    pdf.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="storybook.pdf", mimetype="application/pdf")

@app.route("/logout")
def logout():
    session.clear()
    return render_template('index.html')

def get_recommended_topics(history_list):
    prompt = (
        "You are a children's story assistant. Based on the user's previous stories below:\n"
        + "\n".join(f"- {item}" for item in history_list) +
        "\n\nRecommend 3 new story topics in the following format:\n"
        "Field: <subject>\n"
        "Topic: <new topic>\n"
        "Reason: <why it's relevant based on past topics>\n\n"
        "Respond with 3 sets in this format, separated by blank lines."
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": prompt}
        ],
        max_tokens=400
    )

    content = response.choices[0].message.content.strip()
    # Split into 3 blocks
    blocks = content.split("\n\n")
    recs = []
    for block in blocks:
        lines = block.strip().splitlines()
        field = topic = reason = ""
        for line in lines:
            if line.lower().startswith("field:"):
                field = line.split(":", 1)[1].strip()
            elif line.lower().startswith("topic:"):
                topic = line.split(":", 1)[1].strip()
            elif line.lower().startswith("reason:"):
                reason = line.split(":", 1)[1].strip()
        if field and topic:
            recs.append({"field": field, "topic": topic, "reason": reason})
    return recs

@app.route("/view_story/<int:story_id>")
def view_story(story_id):
    conn = sqlite3.connect("projectgpt.db")
    cursor = conn.cursor()

    user_email = session.get("username")
    cursor.execute("SELECT id FROM users WHERE email = ?", (user_email,))
    user_row = cursor.fetchone()

    if not user_row:
        return "User not found", 404

    user_id = user_row[0]
    cursor.execute("SELECT title, story_json, image_json FROM user_stories WHERE id = ? AND user_id = ?", (story_id, user_id))
    row = cursor.fetchone()

    if not row:
        return "Story not found or access denied", 403

    title = row[0]
    pages = json.loads(row[1])
    images = json.loads(row[2])

    return render_template("story_detail.html", title=title, pages=pages, images=images, story_id = story_id)

def split_text(text, max_chars):
    words = text.split()
    lines, line = [], ""
    for word in words:
        if len(line + word) <= max_chars:
            line += word + " "
        else:
            lines.append(line.strip())
            line = word + " "
    lines.append(line.strip())
    return lines



@app.route("/storybook")
def storybook():
    pages, images = [], []
    if os.path.exists(STORY_JSON_PATH):
        with open(STORY_JSON_PATH) as f:
            pages = json.load(f)
        with open(IMAGES_JSON_PATH) as f:
            images = json.load(f)
    return render_template("story_detail.html", pages=pages, images=images)




@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, email, password_hash FROM users WHERE email = ?", (email,))
            result = cursor.fetchone()

        if result and check_password_hash(result[2], password):
            session["user_id"] = result[0]
            session["username"] = result[1]
            flash("Login successful! Welcome back.", "success")
            return redirect(url_for("index"))
        else:
            flash("Invalid credentials. Please try again.", "danger")

    return render_template("login.html")



@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        password_hash = generate_password_hash(password, method="pbkdf2:sha256")


        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                               (name, email, password_hash))
                conn.commit()
            flash("Account created successfully! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered. Please log in.", "warning")

    return render_template("signup.html")



@app.route("/")
def index():
    return render_template('index.html')

def get_user_topic_field_history(user_id, limit=5):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT field, topic FROM user_stories WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        )
        return cursor.fetchall()

import re
def split_story_into_pages(text):
    pattern = r"Page\s+\d+:?\s+(.*?)(?=Page\s+\d+|$)"
    matches = re.findall(pattern, text, re.DOTALL)
    return [match.strip() for match in matches]
def generate_storybook_page_with_text(initialfile, page, result):
    img = Image.open(initialfile).convert("RGBA")
    draw = ImageDraw.Draw(img)

    font = ImageFont.truetype("RobotoMono-Regular.ttf", size = 36)

    max_width = img.width - 80
    lines = []
    words = page.split() # ["word1","word2","word3",...]
    line = ""
    for word in words:
        test_line = f"{line} {word}".strip()
        w, h = draw.textsize(test_line, font=font)
        if w <= max_width:
            line = test_line
        else:
            lines.append(line)
            line = word
    lines.append(line)

    y = img.height - (len(lines) * 45) - 30
    for line in lines:
        draw.text((40,y), line, fill="black", font=font)
        y += 45
    img.save(result)

import base64
def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def calculate_position(image_path):
    base64_image = encode_image(image_path)
    response = client.chat.completions.create(
        model = "gpt-4o",
        messages = [
            {"role:":"user", "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url" : f"data:image/png;base64, {base64_image}"
                    }
                },{
                    "type": "text",
                    "text" :"Where should i overlay this text to make it readable and not block important parts? Reply with top-left, top-center, center, bottom-left, etc."
                }
            ]
             }
        ],
        max_tokens = 20
    )
    position = response.choices[0].message.content.strip()
    return position

def fix_orientation(path):
    """Rotate image if it's horizontal."""
    img = Image.open(path)
    if img.width > img.height:
        img = img.rotate(90, expand=True)
        img.save(path)

def generate_images_for_pages(pages, story_id, character_identity):
    image_paths = []
    for i, page in enumerate(pages):
        prompt = (
            f"Children's storybook illustration in portrait layout (vertical format), "
            f"with a taller height than width (e.g., 1024x1500). "
            f"Do NOT use landscape or horizontal layout. "
            f"Draw using consistent warm watercolor and soft digital painting style. "
            f"Characters must be vertically centered in the scene. "
            f"Keep consistent character design across pages: {character_identity}. "
            f"Do not include any text or title. "
            f"Page scene: {page}"
        )
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                n=1,
                size="1024x1500"
            )
            image_url = response.data[0].url

            img_data = requests.get(image_url).content
            filename = f"{IMAGE_DIR}/raw_story_{story_id}_page_{i+1}.png"
            with open(filename, "wb") as f:
                f.write(img_data)

            fix_orientation(filename)  # auto-rotate if needed
            image_paths.append("/" + filename)
        except Exception as e:
            print(f"Image error on page {i+1}: {e}")
            image_paths.append("/static/images/default.jpg")
    return image_paths
@app.route("/generate", methods=["GET", "POST"])
def generate():
    pages, images = [], []
    field = ""
    topic = ""
    grade = ""
    title = ""
    subtitle = ""

    if request.method == "POST":
        field = request.form["field"]
        topic = request.form["topic"]
        grade = request.form["grade"]
        age = request.form["age"]
        gender = request.form["gender"]

        prompt = (
            f"Write a 12 pages of creative children's storybook for a {gender} student in grade {grade} (age {age}) "
            f"about '{topic}' in the field of {field}. Make it fun, educational, and age-appropriate.\n\n"
            f"""Example: 
            Title: "The Amazing Coin Collector"
            Page 1
            The Amazing Coin Collector

            Page 2
            Max loved animals but his piggy bank was empty again. "I wish I had more money to help the animals."

            Page 3
            Grandpa smiled, "I have something for you!" 
            It was a dusty old coin album.
            ...
            """
        )

        try:
            job_id = "ftjob-oZvoFYGdnXslXILuRtsnDXKk"
            job_info = client.fine_tuning.jobs.retrieve(job_id)
            ourmodel = job_info.fine_tuned_model

            response = client.chat.completions.create(
                model=ourmodel,
                messages=[
                    {"role": "system", "content": "You are a friendly AI that tells helpful, age-appropriate stories to children."},
                    {"role": "user", "content": prompt}
                ]
            )

            story = response.choices[0].message.content
            pages = split_story_into_pages(story)

            if pages:
                lines = pages[0].split("\n")
                title = lines[0].strip()
                subtitle = lines[1].strip() if len(lines) > 1 else ""

                # Character identity extraction
                identity_prompt = f"""
                Extract the main character's appearance description for consistent illustrations based on this story excerpt:

                \"\"\"{pages[0]}\"\"\"

                Describe the main character in 1 sentence (appearance, clothes, mood). Do not include names or story details.
                """

                identity_response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": identity_prompt}],
                    max_tokens=60
                )
                character_identity = identity_response.choices[0].message.content.strip()
            else:
                character_identity = ""

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(id) FROM user_stories")
            max_id = cursor.fetchone()[0] or 0
            story_id = max_id + 1

            images = generate_images_for_pages(pages, story_id, character_identity)

            with open(STORY_JSON_PATH, "w") as f:
                json.dump(pages, f)
            with open(IMAGES_JSON_PATH, "w") as f:
                json.dump(images, f)

        except Exception as e:
            print("Story generation error:", e)
            pages = [f"Error generating story: {e}"]

        if "user_id" in session:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute(
                    "INSERT INTO user_stories (user_id, title, field, topic, grade, story_json, image_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        session["user_id"],
                        title,
                        field,
                        topic,
                        grade,
                        json.dumps(pages),
                        json.dumps(images),
                        created_at
                    )
                )
                conn.commit()

    return render_template("generate.html", pages=pages, images=images, field=field, topic=topic, grade=grade, title=title, subtitle=subtitle, story_id=story_id if pages else None)



@app.route("/profile")
def profile():
    if "user_id" not in session:
        flash("Please log in to view your profile.", "warning")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        # Username
        cursor.execute("SELECT name FROM users WHERE id = ?", (user_id,))
        user_info = cursor.fetchone()

        # Get all stories
        cursor.execute(
            "SELECT id, title, field, topic, grade, created_at, image_json "
            "FROM user_stories WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        story_rows = cursor.fetchall()

        stories = []
        latest_story_id = None
        for row in story_rows:
            story_id, title, field, topic, grade, created_at, image_json = row
            latest_story_id = latest_story_id or story_id
            try:
                images = json.loads(image_json)
                cover_image = images[0] if images else None
            except Exception:
                cover_image = None
            stories.append((story_id, title, field, topic, grade, created_at, cover_image))

        # Get cached recommendation if any
        cursor.execute("SELECT recommendations, last_story_id FROM user_recommendations WHERE user_id = ?", (user_id,))
        rec_row = cursor.fetchone()

        recommended_topics = []
        if stories:
            if rec_row is None or int(rec_row[1]) != latest_story_id:
                # Recalculate
                recent_history = [f"{story[2]} - {story[3]}" for story in stories[:5]]
                recommended_topics = get_recommended_topics(recent_history)
                json_recs = json.dumps(recommended_topics)

                # Insert or update
                cursor.execute("""
                    INSERT INTO user_recommendations (user_id, recommendations, last_story_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET recommendations = ?, last_story_id = ?
                """, (user_id, json_recs, latest_story_id, json_recs, latest_story_id))
                conn.commit()
            else:
                recommended_topics = json.loads(rec_row[0])

    return render_template("profile.html", username=user_info[0], stories=stories, recommended=recommended_topics)



@app.template_filter('datetimeformat')
def datetimeformat(value):
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%b %d")  # E.g., "Jun 29"
    except:
        return value
if __name__ == "__main__":
    app.run(debug=True)
