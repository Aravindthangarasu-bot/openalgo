import re

text = "TARGET:- 105/110/120+"

target_section_match = re.search(
    r'(?:target|tgt|tp)s?\s*[:\s-]*([\d\s,./+]+?)(?=sl|stop|above|below|\n|$)',
    text,
    re.I
)

print(f"Target section match: {target_section_match}")
if target_section_match:
    target_str = target_section_match.group(1)
    print(f"Target string: '{target_str}'")
    potential_targets = re.findall(r'\d+(?:\.\d+)?', target_str)
    print(f"Potential targets: {potential_targets}")
