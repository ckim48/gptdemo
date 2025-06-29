from openai import OpenAI
from elevenlabs import ElevenLabs
from pydub import AudioSegment
import re
import io
import json


available_voices = {
    "Narrator": 'pMsXgVXv3BLzUgSXRplE',
    "Young girl": 'z9fAnlkpzviPz146aGWa',
    "Funny girl": 'jsCqWAovK2LkecY7zXl4',
    "Deep Male": 'onwK4e9ZLuTAKqWW03F9',
    "Playful Boy": 'D38z5RcWu1voky8WS1ja',
    "Monster": 'JBFqnCBsd6RMkjVDRZzb',
}

# Converting regular storybook into speaker-line format
def process_page_to_lines(page_text, page_number):
    prompt = f"""
You are converting a story page into speaker-line format with clear attributions.

Page {page_number} content:
\"\"\"
{page_text}
\"\"\"

Follow these rules:
- Start with `Page {page_number}` on the first line.
- Break content into speaker-labeled lines in this format:
  Narrator^ "Text..."
  CharacterName^ "Dialog..."
- Include narration as `Narrator`.
- Do not add or change any dialog.
- Do not include placeholder text like "Let's go!" unless it's in the original.

Now output the speaker-line version:
"""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    content = response.choices[0].message.content.strip()
    print(f"\n--- Processed Page {page_number} ---\n{content}\n")
    return content

def detect_speak(line):
    m = re.match(r'^([\w\s]+)\^', line)
    return m.group(1).strip() if m else "Narrator"

def classify_characters(characters):
    prompt = f"""
Classify these characters into one of the following voice types: {list(available_voices.keys())}
Characters: {', '.join(characters)}

Respond in JSON format like:
{{ "Felix": "Playful Boy", "Dragon": "Monster" }}
"""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}]
    )
    content = response.choices[0].message.content
    try:
        content = content.strip("```json").strip("```").strip()
        return json.loads(content)
    except Exception as e:
        print("Failed to parse classification.")
        print(content)
        raise e

def generate_audio(text, voice_id):
    audio = client_api.text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id="eleven_monolingual_v1",
        voice_settings={
            'stability': 0.4,
            'similarity_boost': 0.7
        }
    )
    return b"".join(audio)

def combine_audios(audio_chunks, add_pause=True):
    final_audio = AudioSegment.empty()
    pause = AudioSegment.silent(duration=500) if add_pause else None
    for chunk in audio_chunks:
        segment = AudioSegment.from_file(io.BytesIO(chunk), format="mp3")
        final_audio += segment
        if add_pause:
            final_audio += pause
    return final_audio

def generate_storybook_audio(pages,title="Unavailable"):
    all_characters = set(["Narrator"])
    structured_lines = []

    for idx, page_text in enumerate(pages):
        page_number = idx + 1
        page_lines_raw = process_page_to_lines(page_text, page_number)
        lines = page_lines_raw.strip().split('\n')
        page_lines = []
        for line in lines:
            if not line.strip() or line.startswith("Page"):
                continue
            speaker = detect_speak(line)
            line_text = re.sub(r'^[\w\s]+\^\s*', '', line)
            page_lines.append((speaker, line_text))
            all_characters.add(speaker)
        structured_lines.append(page_lines)

    classification = classify_characters(all_characters)

    title_audio = generate_audio(title, available_voices["Narrator"])
    title_segment = AudioSegment.from_file(io.BytesIO(title_audio), format="mp3")
    full_audio = title_segment + AudioSegment.silent(duration=500)

    for idx, page in enumerate(structured_lines):
        page_chunks = []
        for speaker, line in page:
            voice_category = classification.get(speaker, "Narrator")
            voice_id = available_voices.get(voice_category, available_voices["Narrator"])
            try:
                chunk = generate_audio(line, voice_id)
                page_chunks.append(chunk)
            except Exception as e:
                print(f"Error on Page {idx+1}, line: {line}")
        combined = combine_audios(page_chunks)
        combined.export(f"page_{idx+1}.mp3", format="mp3")
        full_audio += combined + AudioSegment.silent(duration=500)

    full_audio.export("storybook.mp3", format="mp3")
    return "storybook.mp3"

def merge_audio(narration_path ="narration.mp3", bg_music_path="bg_music.mp3", output_path="final_mix.mp3"):
  narration = AudioSegment.from_file(narration_path)
  bg_music = AudioSegment.from_file(bg_music_path)

  # Loop background music if it's shorter than narration.
  if len(bg_music) < len(narration):
    repeat_times = int(len(narration)/len(bg_music)) + 1
    bg_music = bg_music * repeat_times

    combined = narration.overlay(bg_music)
    combined.export(output_path, format="mp3")
# # Run it
# generate_storybook_audio()
