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
.venv/bin/python -m pytest                     # full suite (~3000 tests)
.venv/bin/python -m pytest --snapshot-update   # re-bless goldens after an intentional visual change
```

On a snapshot mismatch the failure message points at
`tests/output/diff/{case}_{expected,actual,diff}.png` (magenta = changed
pixels). Commit updated goldens together with the code change so the visual
delta is reviewable in the git diff.

## Contact sheets (human review)

```bash
cd engine
PYTHONPATH=. .venv/bin/python -m tests.framework.contact_sheet --app sports --scale 3
```

Writes `tests/output/sports_h32.png` / `sports_h64.png`: every fixture
rendered at every width, upscaled with NEAREST so the pixel grid stays
visible. Always renders live code (not the goldens).

## Layout structure tests

`apps/sports/tests/test_layout.py` asserts on the `PlacedBox` audit trail every card
render produces (via `libraries/layout`): no overlapping elements, nothing
clipped or out of bounds, required elements present per tier, and the score
at least as prominent as the team name. These hold for any new fixture
automatically — snapshots catch visual regressions, these catch structural
ones.

## Test data

Tests are co-located with their apps and libraries:

- `apps/{app}/tests/fixtures.py` — fixture payloads for the app's snapshot suite
- `apps/{app}/tests/snapshots/{app}/` — committed golden PNGs
- `apps/{app}/tests/test_snapshots.py` — parametrized snapshot runner
- `apps/{app}/tests/test_*.py` — other app-specific tests
- `libraries/{lib}/tests/test_*.py` — library unit tests
- `tests/framework/` — shared harness, comparison, clock, logo utilities

Apps whose frames depend on the current time (weather, countdown, world clock) are
rendered with `datetime.now()` frozen to `tests/framework/clock.py::FIXED_NOW`.

Logos are deterministic generated placeholders (team-color shields/flags).
Optionally commit real PNGs to `apps/sports/tests/logos/{league}/{ABBR}.png`
(run `python -m tests.framework.fetch_fixture_logos` on a machine with
network access); they take precedence and tests must then be re-blessed.

## Adding snapshot coverage for another app

1. Create `apps/{app}/tests/__init__.py` (empty) and `apps/{app}/tests/fixtures.py`
   with fixture payloads `{"config": {...}, "seed": callable | None}` — the seed
   injects the data `fetch_data` would have fetched — and register:
   `harness.register(SnapshotSuite(app_id, fixtures, harness.CORE_SIZES,
   harness.app_case_render(AppCls, freeze_datetime=... )))`.
2. Add the module to `_SUITE_MODULES` in `tests/framework/harness.py`.
3. Create `apps/{app}/tests/test_snapshots.py` following the pattern of any
   existing per-app test file.
4. Run with `--snapshot-update` to create the goldens, review the contact
   sheet (`python -m tests.framework.contact_sheet --app {app}`), and commit.
