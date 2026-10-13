from pathlib import Path


path = Path("/opt/ai-content-loop/repo/ai_content_loop/generation.py")
data = path.read_bytes()
patterns = (
    (
        b'    "missing_source_link",\r\n    "high_risk_advice",',
        b'    "missing_source_link",\r\n    "below_target_length",\r\n    "high_risk_advice",',
    ),
    (
        b'    "missing_source_link",\n    "high_risk_advice",',
        b'    "missing_source_link",\n    "below_target_length",\n    "high_risk_advice",',
    ),
)
matches = [(old, new) for old, new in patterns if old in data]
if len(matches) != 1 or b'    "below_target_length",' in data:
    raise SystemExit("unexpected generation.py rule block")
old, new = matches[0]
path.write_bytes(data.replace(old, new, 1))
