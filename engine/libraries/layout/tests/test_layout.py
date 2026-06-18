"""Unit tests for the layout primitives library."""

from __future__ import annotations

import pytest
from PIL import Image

from libraries.layout.library import (
    Frame,
    LayoutOverflow,
    Region,
    TextSpec,
    first_fitting,
    fit_font_size,
    measure,
)


def _img(w: int, h: int, color=(255, 0, 0)) -> Image.Image:
    return Image.new("RGB", (w, h), color)


class TestRegion:
    def test_take_left_partitions(self):
        left, rest = Region(0, 0, 100, 32).take_left(30)
        assert (left.x, left.w) == (0, 30)
        assert (rest.x, rest.w) == (30, 70)
        assert left.h == rest.h == 32

    def test_take_right_partitions(self):
        right, rest = Region(10, 5, 100, 32).take_right(30)
        assert (right.x, right.w) == (80, 30)
        assert (rest.x, rest.w) == (10, 70)

    def test_take_bottom_partitions(self):
        bottom, rest = Region(0, 0, 64, 64).take_bottom(12)
        assert (bottom.y, bottom.h) == (52, 12)
        assert (rest.y, rest.h) == (0, 52)

    def test_take_clamps_to_available(self):
        left, rest = Region(0, 0, 20, 10).take_left(50)
        assert left.w == 20
        assert rest.w == 0

    def test_split_rows_last_absorbs_remainder(self):
        rows = Region(0, 0, 10, 23).split_rows(2)
        assert [r.h for r in rows] == [11, 12]
        assert rows[1].bottom == 23

    def test_split_cols_last_absorbs_remainder(self):
        cols = Region(0, 0, 23, 10).split_cols(2)
        assert [c.w for c in cols] == [11, 12]
        assert cols[1].right == 23

    def test_inset(self):
        r = Region(0, 0, 20, 10).inset(2, 1)
        assert (r.x, r.y, r.w, r.h) == (2, 1, 16, 8)

    def test_center(self):
        r = Region(10, 10, 20, 10)
        assert (r.cx, r.cy) == (20, 15)


class TestFramePlace:
    def test_anchors(self):
        frame = Frame(20, 10)
        region = Region(0, 0, 20, 10)
        cases = {
            "lt": (0, 0), "mt": (7, 0), "rt": (14, 0),
            "lm": (0, 3), "mm": (7, 3), "rm": (14, 3),
            "lb": (0, 6), "mb": (7, 6), "rb": (14, 6),
        }
        for anchor, (ex, ey) in cases.items():
            box = frame.place(anchor, _img(6, 4), region, anchor=anchor)
            assert (box.x, box.y) == (ex, ey), anchor

    def test_overflow_raises(self):
        frame = Frame(20, 10)
        with pytest.raises(LayoutOverflow):
            frame.place("big", _img(30, 4), Region(0, 0, 20, 10))

    def test_overflow_clips_when_allowed(self):
        frame = Frame(20, 10)
        box = frame.place("big", _img(30, 4), Region(0, 0, 20, 10), allow_clip=True)
        assert box.clipped
        assert box.w == 20
        assert frame.image.getpixel((19, 0)) == (255, 0, 0)

    def test_rgba_composites_through_alpha(self):
        frame = Frame(4, 4)
        rgba = Image.new("RGBA", (4, 4), (0, 255, 0, 0))
        rgba.putpixel((1, 1), (0, 255, 0, 255))
        frame.place("a", rgba, Region(0, 0, 4, 4))
        assert frame.image.getpixel((1, 1)) == (0, 255, 0)
        assert frame.image.getpixel((0, 0)) == (0, 0, 0)

    def test_boxes_recorded(self):
        frame = Frame(20, 10)
        frame.place("a", _img(5, 5), Region(0, 0, 10, 10), priority=0)
        assert frame.boxes[0].name == "a"
        assert frame.boxes[0].priority == 0


class TestOverlap:
    def test_disjoint_boxes_do_not_overlap(self):
        frame = Frame(20, 10)
        frame.place("a", _img(5, 5), Region(0, 0, 5, 10))
        frame.place("b", _img(5, 5), Region(10, 0, 5, 10))
        assert frame.overlapping_pairs() == []

    def test_overlapping_boxes_detected(self):
        frame = Frame(20, 10)
        frame.place("a", _img(8, 8), Region(0, 0, 20, 10))
        frame.place("b", _img(8, 8), Region(4, 0, 20, 10))
        pairs = frame.overlapping_pairs()
        assert len(pairs) == 1
        assert {pairs[0][0].name, pairs[0][1].name} == {"a", "b"}

    def test_min_gap(self):
        frame = Frame(20, 10)
        frame.place("a", _img(5, 10), Region(0, 0, 5, 10))
        frame.place("b", _img(5, 10), Region(6, 0, 5, 10))  # 1px apart
        assert frame.overlapping_pairs(min_gap=0) == []
        assert len(frame.overlapping_pairs(min_gap=2)) == 1

    def test_ignore_pairs(self):
        frame = Frame(20, 10)
        frame.place("a", _img(8, 8), Region(0, 0, 20, 10))
        frame.place("b", _img(8, 8), Region(4, 0, 20, 10))
        assert frame.overlapping_pairs(ignore=[("a", "b")]) == []


class TestTextFitting:
    def test_measure_matches_render(self):
        spec = TextSpec("BOS", 12, bold=True)
        from libraries.layout.library import text_img

        assert measure(spec) == text_img(spec, (255, 255, 255)).size

    def test_fit_font_size_respects_height(self):
        size = fit_font_size("0", 10)
        assert size is not None
        _w, h = measure(TextSpec("0", size))
        assert h <= 10

    def test_fit_font_size_respects_width(self):
        narrow = fit_font_size("00000000", 28, max_w=20)
        wide = fit_font_size("00000000", 28, max_w=200)
        assert narrow is None or narrow < (wide or 0)

    def test_fit_font_size_none_when_impossible(self):
        assert fit_font_size("WWWWWWWW", 28, max_w=2) is None

    def test_fit_font_size_allow_large(self):
        size = fit_font_size("0", 50, allow_large=True)
        assert size is not None and size > 28
        _w, h = measure(TextSpec("0", size))
        assert h <= 50

    def test_first_fitting_prefers_earlier(self):
        long = TextSpec("Mississippi State", 12)
        short = TextSpec("MSST", 12)
        assert first_fitting(500, [long, short]) == long
        assert first_fitting(measure(short)[0], [long, short]) == short

    def test_first_fitting_none(self):
        assert first_fitting(1, [TextSpec("WW", 12)]) is None

    def test_first_fitting_skips_empty(self):
        assert first_fitting(100, [TextSpec("", 12), TextSpec("A", 12)]).text == "A"
