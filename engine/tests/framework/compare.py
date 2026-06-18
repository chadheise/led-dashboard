"""Golden-image comparison for snapshot tests.

Comparison is exact byte equality of RGB pixels — on an LED matrix every pixel
is deliberate, so there is no tolerance. On mismatch the expected, actual, and
a magenta-highlighted diff image are written under ``tests/output/diff/`` and
the test fails with their paths.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops

TESTS_DIR = Path(__file__).parent.parent        # engine/tests/
ENGINE_DIR = Path(__file__).parent.parent.parent  # engine/
DIFF_DIR = TESTS_DIR / "output" / "diff"

_DIFF_COLOR = (255, 0, 255)


def snapshot_path(app_id: str, name: str) -> Path:
    return ENGINE_DIR / "apps" / app_id / "tests" / "snapshots" / f"{name}.png"


def _write_diff_artifacts(name: str, expected: Image.Image, actual: Image.Image) -> Path:
    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    expected.save(DIFF_DIR / f"{name}_expected.png")
    actual.save(DIFF_DIR / f"{name}_actual.png")

    if expected.size == actual.size:
        delta = ImageChops.difference(expected, actual).convert("L")
        mask = delta.point(lambda p: 255 if p > 0 else 0)
        diff = actual.copy()
        diff.paste(_DIFF_COLOR, mask=mask)
    else:
        diff = Image.new("RGB", actual.size, _DIFF_COLOR)
    diff_path = DIFF_DIR / f"{name}_diff.png"
    diff.save(diff_path)
    return diff_path


def assert_snapshot(image: Image.Image, app_id: str, name: str, update: bool) -> None:
    """Compare image against the committed golden, or rewrite it when updating."""
    image = image.convert("RGB")
    path = snapshot_path(app_id, name)

    if update:
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        return

    if not path.exists():
        raise AssertionError(
            f"Missing golden snapshot {path}.\n"
            f"Run `pytest --snapshot-update` to create it, then commit the PNG."
        )

    expected = Image.open(path).convert("RGB")
    if expected.size == image.size and expected.tobytes() == image.tobytes():
        return

    diff_path = _write_diff_artifacts(name, expected, image)
    raise AssertionError(
        f"Snapshot mismatch for {app_id}/{name} "
        f"(expected {expected.size}, got {image.size}).\n"
        f"Inspect {diff_path} (magenta = changed pixels).\n"
        f"If the change is intentional, re-bless with `pytest --snapshot-update`."
    )
