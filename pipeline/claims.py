"""Walk the scenes JSON claim by claim (PLAN.md section 4).

A claim is each voiceover line, each on-screen text, and each visual item (label and
value pair). The checker and the fact sheet both use this list, so they always agree
on what a claim is.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

# Element names for visual items, by visual type (used in messages and the fact sheet).
ITEM_ELEMENT = {
    "bar_chart": "bar",
    "price_cards": "price card",
    "big_number": "big number",
}


@dataclass
class Claim:
    scene_id: object
    scene_index: int
    kind: str  # voiceover | on_screen | item
    element: str  # voiceover, headline, sub, bullet, quote, bar, price card, big number
    where: str  # voiceover[0], on_screen[1], visual.items[2]
    text: str
    source_ids: list[int] = field(default_factory=list)
    spoken: str | None = None
    label: str | None = None
    value: str | None = None
    claim_owner: str = "none"

    @property
    def is_claim(self) -> bool:
        """Text with no source_ids makes no claim (only allowed without numbers)."""
        return bool(self.source_ids)


def iter_claims(doc: dict) -> list[Claim]:
    out: list[Claim] = []
    for idx, scene in enumerate(doc.get("scenes") or []):
        if not isinstance(scene, dict):
            continue
        sid = scene.get("id", idx + 1)
        owner = scene.get("claim_owner", "none")
        for k, line in enumerate(scene.get("voiceover") or []):
            if isinstance(line, dict):
                out.append(Claim(sid, idx, "voiceover", "voiceover", f"voiceover[{k}]",
                                 str(line.get("text", "")), list(line.get("source_ids") or []),
                                 spoken=line.get("spoken"), claim_owner=owner))
        for k, item in enumerate(scene.get("on_screen") or []):
            if isinstance(item, dict):
                out.append(Claim(sid, idx, "on_screen", str(item.get("role", "text")), f"on_screen[{k}]",
                                 str(item.get("text", "")), list(item.get("source_ids") or []),
                                 claim_owner=owner))
        visual = scene.get("visual") or {}
        element = ITEM_ELEMENT.get(visual.get("type"), "item")
        for k, item in enumerate(visual.get("items") or []):
            if isinstance(item, dict):
                label, value = str(item.get("label", "")), str(item.get("value", ""))
                out.append(Claim(sid, idx, "item", element, f"visual.items[{k}]",
                                 f"{label}: {value}", list(item.get("source_ids") or []),
                                 label=label, value=value, claim_owner=owner))
    return out


def voiceover_text(scene: dict) -> str:
    return " ".join(str(line.get("text", "")) for line in scene.get("voiceover") or [] if isinstance(line, dict))


def content_sha256(doc: dict) -> str:
    """Hash of the scenes JSON without the fields later stages fill in.

    `spoken` (tts) and `duration_s` (tts) change after verify; everything the
    checker looked at is covered.
    """

    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in ("spoken", "duration_s")}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x

    data = json.dumps(strip(doc), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()
