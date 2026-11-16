"""Run the pretrained xView2 baseline (INFERENCE_MODE=docker) on every demo pair
and save the results under data/demo/pretrained_results/.

Requires the inference image (docker compose --profile build-ml build ml) and a
host Docker daemon. Run from the repo root on the host, not inside a container:

    python scripts/precompute_pretrained.py

For each pair it writes the raw xView2 mask (pixel values 0-4), a colour overlay
on the post image, and summary.json with zone scores plus, for pairs that ship
xBD ground truth, pixel metrics for both the pretrained model and the stub
heuristic so the two can be compared on the same images.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.config import settings  # noqa: E402
from app.services.inference import (  # noqa: E402
    _make_stub_mask,
    _run_docker_baseline,
    list_demo_pairs,
    resolve_demo_target,
)
from app.services.scoring import OVERLAY_COLORS, score_mask  # noqa: E402

OUT_DIR = settings.demo_data_dir / "pretrained_results"


def overlay(post_path: Path, mask: np.ndarray) -> Image.Image:
    base = Image.open(post_path).convert("RGBA")
    if base.size != (mask.shape[1], mask.shape[0]):
        base = base.resize((mask.shape[1], mask.shape[0]))
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    for cls, color in OVERLAY_COLORS.items():
        if cls:
            rgba[mask == cls] = color
    return Image.alpha_composite(base, Image.fromarray(rgba, mode="RGBA")).convert("RGB")


def pixel_metrics(pred: np.ndarray, gt: np.ndarray) -> dict:
    """Damage (classes 2-4) and building (classes 1-4) agreement with ground truth."""

    def scores(p: np.ndarray, g: np.ndarray) -> dict:
        tp = int((p & g).sum())
        fp = int((p & ~g).sum())
        fn = int((~p & g).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        iou = tp / (tp + fp + fn) if tp + fp + fn else 0.0
        return {k: round(v, 3) for k, v in
                {"precision": precision, "recall": recall, "f1": f1, "iou": iou}.items()}

    return {
        "damage": scores(pred >= 2, (gt >= 2) & (gt <= 4)),
        "building": scores(pred >= 1, (gt >= 1) & (gt <= 4)),
    }


def zone_summary(mask_path: Path) -> dict:
    result = score_mask(mask_path, settings.grid_rows, settings.grid_cols)
    return {
        "summary": result.summary.model_dump(),
        "top_zones": [
            {"rank": z.rank, "bbox": z.bbox, "priority_score": z.priority_score,
             "building_counts": z.building_counts.model_dump()}
            for z in result.zones[:5]
        ],
        "zone_count": len(result.zones),
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    images = settings.demo_data_dir / "images"
    report: dict = {"model": "xView2 baseline (TensorFlow 1.15, pretrained weights)",
                    "image": settings.xview2_docker_image, "pairs": {}}

    for pair in list_demo_pairs():
        pid = pair["id"]
        pre, post = images / pair["pre_image"], images / pair["post_image"]
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / pid
            started = time.monotonic()
            mask_src = _run_docker_baseline(pre, post, job)
            seconds = round(time.monotonic() - started, 1)
            mask_path = OUT_DIR / f"{pid}_mask.png"
            shutil.copyfile(mask_src, mask_path)
            stub_path, _ = _make_stub_mask(pre, post, Path(tmp) / "stub")
            stub = np.array(Image.open(stub_path))

        mask = np.array(Image.open(mask_path))
        overlay(post, mask).save(OUT_DIR / f"{pid}_overlay.jpg", quality=85)
        entry = {"seconds": seconds, **zone_summary(mask_path)}

        target = resolve_demo_target(post)
        if target is not None:
            gt = np.array(Image.open(target))
            entry["vs_ground_truth"] = {
                "pretrained": pixel_metrics(mask, gt),
                "stub": pixel_metrics(stub, gt),
            }
        report["pairs"][pid] = entry
        print(f"{pid}: {seconds}s", entry.get("vs_ground_truth", {}).get("pretrained", ""))

    (OUT_DIR / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_DIR}")


if __name__ == "__main__":
    main()
