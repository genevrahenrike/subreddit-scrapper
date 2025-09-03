import os
import re
from glob import glob
from typing import Dict, List, Optional, Tuple

def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def out_path_for_input(output_dir: str, input_path: str) -> str:
    base = os.path.basename(input_path)
    base = re.sub(r"\.json$", "", base, flags=re.IGNORECASE)
    return os.path.join(output_dir, f"{base}.keywords.jsonl")


def _build_frontpage_index(frontpage_glob: Optional[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    Build index canonical_key -> frontpage_path for fast lookup.
    Returns (index_map, list_of_paths)
    """
    if not frontpage_glob:
        return {}, []
    paths = sorted(glob(frontpage_glob))
    index: Dict[str, str] = {}
    for p in paths:
        # Expect .../output/subreddits/NAME/frontpage.json
        m = re.search(r"/subreddits/([^/]+)/frontpage\.json$", p)
        if not m:
            continue
        folder = m.group(1)
        key = folder.lower()
        index[key] = p
    return index, paths