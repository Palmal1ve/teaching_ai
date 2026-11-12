"""Builds a short synthetic lecture with a known timeline, for smoke tests.

The narration is real speech from macOS `say`, so Whisper has real work to do. The video has a
hidden slide, a backward jump, and a code demo where no slide is on screen.

    cd backend && uv run python ../scripts/make_sample_lecture.py OUT_DIR
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.util import Inches

WIDTH, HEIGHT = 1280, 720
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"

SLIDES = [
    ("Shortest paths", ["Algorithms 101", "Lesson 4", "Weighted directed graphs"],
     "Welcome back. Today we study shortest paths in weighted graphs.", "", False),
    ("Dijkstra's algorithm", ["Greedy choice of the closest vertex", "Priority queue of distances",
                              "Needs non negative edge weights"],
     "Dijkstra's algorithm makes a greedy choice. It always takes the closest unvisited vertex "
     "from a priority queue. Remember it only works with non negative edge weights.",
     "Stress the non negative condition.", False),
    ("Internal answer key", ["Hidden from students", "Exam question three solution"],
     "", "Never shown in class.", True),
    ("Edge relaxation",
     ["If d of v exceeds d of u plus w", "Update d of v", "Repeat for every edge"],
     "Relaxation is the heart of it. If the distance to v is greater than the distance to u plus "
     "the edge weight, we update it. You will be asked to trace this by hand on the exam.",
     "This appears on the midterm every year.", False),
    ("Bellman Ford", ["Handles negative edges", "Relaxes every edge V minus one times",
                      "Detects negative cycles"],
     "Bellman Ford is slower but it handles negative edges. It relaxes every edge V minus one "
     "times, and a further pass detects negative cycles.", "", False),
]

# (slide index or None for the code demo, narration override)
SCRIPT = [
    (0, None),
    (1, None),
    (3, None),
    (None, "Let me switch to a terminal and run this on a small graph. You can see the program "
           "printing every distance as it goes through the vertices."),
    (4, None),
    (1, "Going back to Dijkstra for a moment. Notice that the greedy choice is why negative "
        "edges break it."),
]


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def draw_slide(title: str, bullets: list[str], path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 110), fill=(28, 60, 110))
    draw.text((50, 30), title, font=font(52), fill="white")
    for index, bullet in enumerate(bullets):
        draw.text((80, 180 + index * 90), f"- {bullet}", font=font(40), fill=(20, 20, 20))
    image.save(path)


def draw_demo(path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), (12, 14, 18))
    draw = ImageDraw.Draw(image)
    for index in range(10):
        draw.text((40, 40 + index * 60), f"$ ./run --vertex {index} ok", font=font(30),
                  fill=(120, 230, 140))
    image.save(path)


def make_deck(path: Path) -> None:
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    for title, bullets, _, notes, hidden in SLIDES:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = "\n".join(bullets)
        if notes:
            slide.notes_slide.notes_text_frame.text = notes
        if hidden:
            slide._element.set("show", "0")
    deck.save(str(path))


def speak(text: str, path: Path) -> float:
    subprocess.run(["say", "-r", "170", "-o", str(path), text], check=True)
    wave = path.with_suffix(".wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-ar", "44100",
                    "-ac", "1", str(wave)], check=True)
    probe = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "csv=p=0", str(wave)])
    return float(probe) + 1.0


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    make_deck(out / "lecture.pptx")
    draw_demo(out / "demo.png")
    for index, (title, bullets, *_) in enumerate(SLIDES):
        draw_slide(title, bullets, out / f"slide{index}.png")

    parts, labels, cursor = [], [], 0.0
    for index, (slide, narration) in enumerate(SCRIPT):
        text = narration or SLIDES[slide][2]
        seconds = speak(text, out / f"voice{index}.aiff")
        image = out / ("demo.png" if slide is None else f"slide{slide}.png")
        part = out / f"part{index}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "10",
             "-i", str(image),
             "-i", str(out / f"voice{index}.wav"), "-af", "apad", "-t", f"{seconds:.3f}",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
             "-c:a", "aac", "-ar", "44100", str(part)],
            check=True,
        )
        parts.append(part)
        labels.append({
            "start_ms": int(cursor * 1000),
            "end_ms": int((cursor + seconds) * 1000),
            "slide": None if slide is None else slide + 1,
        })
        cursor += seconds

    listing = out / "parts.txt"
    listing.write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
                    str(listing), "-c", "copy", str(out / "lecture.mp4")], check=True)
    (out / "labels.json").write_text(json.dumps(labels, indent=1))
    print(f"{cursor:.0f} seconds, {len(labels)} spans, in {out}")


if __name__ == "__main__":
    main()
