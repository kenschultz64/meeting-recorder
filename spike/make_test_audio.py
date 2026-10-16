"""Build a synthetic 2-speaker meeting recording for pipeline testing."""
import subprocess
from gtts import gTTS

lines = [
    ("A", "Good morning everyone, thanks for coming. Let's start with the budget review for the building fund."),
    ("B", "Sure. We spent about forty two thousand dollars last quarter, which is under our fifty thousand cap."),
    ("A", "That's good news. What about the roof work? Any update from the contractor?"),
    ("B", "They quoted us eighteen thousand, but I think we should get a second bid before we commit."),
    ("A", "Agreed. Action item: get a second roofing bid by the end of the month. Anything else?"),
    ("B", "Just one thing. We need to confirm the volunteer schedule for the fall outreach event."),
]

files = []
for i, (spk, text) in enumerate(lines):
    tts = gTTS(text, lang="en", slow=False)
    f = f"seg{i}.mp3"
    tts.save(f)
    files.append(f)

inputs = []
for f in files:
    inputs += ["-i", f]
filt = ";".join(
    f"[{i}:a]asetrate=24000*{1.0 if lines[i][0]=='A' else 0.85},aresample=16000[at{i}]"
    for i in range(len(files))
)
filt += ";" + "".join(f"[at{i}]" for i in range(len(files))) + f"concat=n={len(files)}:v=0:a=1[out]"
subprocess.run(
    ["ffmpeg", "-y", "-v", "error"] + inputs
    + ["-filter_complex", filt, "-map", "[out]", "-ar", "16000", "-ac", "1", "meeting_test.wav"],
    check=True,
)
print("made meeting_test.wav")
