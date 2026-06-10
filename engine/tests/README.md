# Engine test suite

Pytest-based, fully offline (no ESPN or CDN calls). Includes a golden-snapshot
framework that renders app fixtures at a matrix of panel sizes and compares
them pixel-for-pixel against committed PNGs.

## Setup

```bash
cd <repo root>
python3 -m venv .venv
.venv/bin/pip install -r engine/requirements.txt -r engine/requirements-dev.txt
```

## Running

```bash
cd engine
../.venv/bin/python -m pytest                     # full suite
../.venv/bin/python -m pytest --snapshot-update   # re-bless goldens after an intentional visual change
```

On a snapshot mismatch the failure message points at
`tests/output/diff/{case}_{expected,actual,diff}.png` (magenta = changed
pixels). Commit updated goldens together with the code change so the visual
delta is reviewable in the git diff.

## Contact sheets (human review)

```bash
cd engine
PYTHONPATH=. ../.venv/bin/python -m tests.snaptest.contact_sheet --app sports --scale 3
```

Writes `tests/output/sports_h32.png` / `sports_h64.png`: every fixture
rendered at every width, upscaled with NEAREST so the pixel grid stays
visible. Always renders live code (not the goldens).

## Layout structure tests

`test_sports_layout.py` asserts on the `PlacedBox` audit trail every card
render produces (via `libraries/layout`): no overlapping elements, nothing
clipped or out of bounds, required elements present per tier, and the score
at least as prominent as the team name. These hold for any new fixture
automatically — snapshots catch visual regressions, these catch structural
ones.

## Test data

- `tests/fixtures/sports.py` — all dev-UI debug games plus stress fixtures
  (near-black colors, 3-digit OT scores, bases loaded, goal overflow,
  missing logos, ...). Add new cases here.
- Logos are deterministic generated placeholders (team-color shields/flags).
  Optionally commit real PNGs to `tests/fixtures/logos/{league}/{ABBR}.png`
  (run `python -m tests.snaptest.fetch_fixture_logos` on a machine with
  network access); they take precedence and tests must then be re-blessed.

## Adding snapshot coverage for another app

1. Create `tests/fixtures/{app}.py` that builds fixture payloads and calls
   `tests.snaptest.harness.register(SnapshotSuite(...))` with a render
   callable `(fixture, w, h) -> RenderResult`. Use
   `harness.render_app_frame` to run a full `DisplayApp` headlessly with
   seeded data.
2. Add the module to `_SUITE_MODULES` in `tests/snaptest/harness.py`.
3. Add a parametrized test like `test_sports_snapshots.py` and run with
   `--snapshot-update` to create the goldens.
