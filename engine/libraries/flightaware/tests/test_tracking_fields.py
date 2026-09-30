"""Extraction of gate/terminal/baggage fields from an AeroAPI flight object.

Flighty's enhanced detail (gate, terminal, baggage belt) comes from the same
FlightAware HyperFeed data the dashboard already pulls via AeroAPI. AeroAPI v4
exposes it on ``/flights/{ident}`` as ``gate_origin``/``gate_destination``/
``terminal_origin``/``terminal_destination``/``baggage_claim`` (all nullable).
``_extract_tracking_fields`` normalizes those into the flight-tracker dict; these
tests pin that mapping and the "" fallback that keeps gate-less cards unchanged.
"""

from __future__ import annotations

from libraries.flightaware.library import _extract_tracking_fields


def test_gate_terminal_baggage_extracted() -> None:
    flight = {
        "ident": "DL699",
        "origin": {"code_iata": "JFK"},
        "destination": {"code_iata": "SEA"},
        "gate_origin": "B22",
        "gate_destination": "A7",
        "terminal_origin": "4",
        "terminal_destination": "S",
        "baggage_claim": "7",
    }
    fields = _extract_tracking_fields(flight)
    assert fields["gate_origin"] == "B22"
    assert fields["gate_dest"] == "A7"
    assert fields["terminal_origin"] == "4"
    assert fields["terminal_dest"] == "S"
    assert fields["baggage_claim"] == "7"


def test_missing_gate_fields_default_to_empty_string() -> None:
    """A flight object with no gate/terminal/baggage keys (or explicit null)
    yields "" so the tracker renders exactly as it did before this data existed."""
    flight = {
        "ident": "AA100",
        "origin": {"code_iata": "JFK"},
        "destination": {"code_iata": "LHR"},
        "gate_origin": None,
        "terminal_destination": None,
    }
    fields = _extract_tracking_fields(flight)
    for key in ("gate_origin", "gate_dest", "terminal_origin", "terminal_dest", "baggage_claim"):
        assert fields[key] == ""
