from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI



def generate_storybook_page_with_text(initialfile, page, result):
    img = Image.open(initialfile).convert("RGBA")
    txt_layer = Image.new("RGBA", img.size, (255, 255, 255, 0))  # Transparent layer
    draw = ImageDraw.Draw(txt_layer)

    font = ImageFont.truetype("static/fonts/RobotoMono-Regular.ttf", size=33)

    max_width = img.width - 80
    lines = []
    words = page.split()
    line = ""

    for word in words:
        test_line = f"{line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            line = test_line
        else:
            lines.append(line)
            line = word
    lines.append(line)

    line_height = 50
    box_height = len(lines) * line_height + 40
    box_width = img.width - 100
    y_start = box_height - 250
    x_start = 50

    position = calculate_position(initialfile)
    if position == "top-left":

    draw.rectangle(
        [(x_start, y_start), (x_start + box_width, y_start + box_height)],
        fill = (255,255,255, 200)
    )
    y = y_start + 20
    for line in lines:
        draw.text((x_start+20, y), line, font=font, fill= (20,20,20, 255))
        y += line_height

    out = Image.alpha_composite(img, txt_layer)
    out.convert("RGB").save(result)

import base64
def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def calculate_position(image_path):
    base64_image = encode_image(image_path)
    response = client.chat.completions.create(
        model = "gpt-4o",
        messages = [
            {"role":"user", "content": [
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

text = "\"What do you mean?\" asked Max, eager to know.\n  \n\"You'll see,\" said Grandpa, handing him a shimmering silver coin.\n \n\"Let's start your amazing adventure as a coin collector!\""
image_path ='static/images/raw_story_c5caf209_page_2.png'
result ='static/images/result_story_f768b48b_page_1.png'
print(calculate_position('static/images/raw_story_c5caf209_page_2.png'))
generate_storybook_page_with_text(image_path,text, result )