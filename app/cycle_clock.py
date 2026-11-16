"""Inline SVGs for the Cycle Clock and the nights chart. Plain strings, so no chart dependency."""

from datetime import date, timedelta
from html import escape
from math import cos, pi, sin

from app.summary import phase_label, window_text
from contracts import DailyRecord, PhaseEstimate

INK, BODY, PLUM, WINE, TRACK, WARM, COOL = (
    "#231c2a",
    "#4e4558",
    "#8a3a68",
    "#7a1f3d",
    "#ece7ef",
    "#2f6f8f",
    "#8d8297",
)
DEFAULT_DIAL_DAYS = 30  # the contract has no cycle length yet, so the dial is drawn at 30 days


def _point(day: float, days: int, r: float) -> tuple[float, float]:
    angle = (day - 1) / days * 2 * pi - pi / 2  # day 1 at the top, clockwise
    return 150 + r * cos(angle), 150 + r * sin(angle)


def _arc(start: float, end: float, days: int, r: float, color: str, width: int) -> str:
    x1, y1 = _point(start, days, r)
    x2, y2 = _point(end, days, r)
    large = 1 if (end - start) / days > 0.5 else 0
    return (
        f'<path d="M{x1:.1f} {y1:.1f} A{r} {r} 0 {large} 1 {x2:.1f} {y2:.1f}" fill="none" '
        f'stroke="{color}" stroke-width="{width}" stroke-linecap="round"/>'
    )


def cycle_clock_svg(est: PhaseEstimate, records: list[DailyRecord]) -> str:
    """The dial: today, any logged bleeding, and the likely window, all from the contracts."""
    day = est.cycle_day
    days = max(DEFAULT_DIAL_DAYS, day or 0)
    start = est.as_of - timedelta(days=(day or 1) - 1)
    day_of = lambda d: (d - start).days + 1  # noqa: E731
    parts = [f'<circle cx="150" cy="150" r="118" fill="none" stroke="{TRACK}" stroke-width="22"/>']

    bleeding = [
        day_of(r.date)
        for r in records
        if r.checkin and r.checkin.bleeding not in (None, "none") and day_of(r.date) >= 1
    ]
    if bleeding:
        parts.append(_arc(min(bleeding), max(bleeding) + 0.8, days, 118, WINE, 8))
    if est.ovulation_window:
        lo, hi = day_of(est.ovulation_window.start), day_of(est.ovulation_window.end)
        parts.append(_arc(lo, max(hi, lo + 0.5), days, 118, PLUM, 22))
    if day:
        x, y = _point(day, days, 118)
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="{INK}" '
            'stroke="#fff" stroke-width="3"/>'
        )
    title = f"Day {day}" if day else "Day unknown"
    label = phase_label(est)
    alt = f"Cycle clock. {title}. {label}. Likely window: {window_text(est) or 'not enough data'}."
    return (
        f'<svg viewBox="0 0 300 330" role="img" aria-label="{escape(alt)}" '
        'style="width:100%;max-width:250px;display:block;margin:auto">'
        + "".join(parts)
        + f'<text x="150" y="20" text-anchor="middle" font-size="13" fill="{BODY}">Day 1</text>'
        f'<text x="150" y="162" text-anchor="middle" font-size="46" font-weight="700" '
        f'fill="{INK}">{title if day else "Day –"}</text>'
        f'<text x="150" y="190" text-anchor="middle" font-size="16" font-weight="600" '
        f'fill="{PLUM}">{escape(label)}</text>'
        f'<rect x="58" y="312" width="18" height="10" rx="3" fill="{PLUM}"/>'
        f'<text x="82" y="322" font-size="14" fill="{BODY}">Likely window</text>'
        f'<circle cx="192" cy="317" r="6" fill="{INK}"/>'
        f'<text x="204" y="322" font-size="14" fill="{BODY}">Today</text></svg>'
    )


def nights_svg(records: list[DailyRecord]) -> str:
    """Skin temp vs. her usual, one column per night. Missing nights say so instead of showing 0."""
    width, height, zero, scale = 320, 150, 70, 80  # scale: pixels per degree C
    step = width / max(len(records), 1)
    parts = [f'<line x1="0" x2="{width}" y1="{zero}" y2="{zero}" stroke="{COOL}"/>']
    for i, r in enumerate(records):
        cx = step * i + step / 2
        label = _short(r.date)
        parts.append(
            f'<text x="{cx:.0f}" y="{height - 4}" text-anchor="middle" font-size="12" '
            f'fill="{BODY}">{label}</text>'
        )
        dev = r.skin_temp_dev_c
        if dev is None:
            parts.append(
                f'<text x="{cx:.0f}" y="{zero - 6}" text-anchor="middle" font-size="12" '
                f'fill="{BODY}">no data</text>'
            )
            continue
        h = max(abs(dev) * scale, 2)
        y = zero - h if dev >= 0 else zero
        color = WARM if dev >= 0 else COOL
        parts.append(
            f'<rect x="{cx - 16:.0f}" y="{y:.0f}" width="32" height="{h:.0f}" fill="{color}"/>'
            f'<text x="{cx:.0f}" y="{y - 4 if dev >= 0 else y + h + 13:.0f}" text-anchor="middle" '
            f'font-size="12" fill="{INK}">{dev:+.1f}</text>'
        )
    alt = "Skin temperature compared with her usual, in degrees C, by night."
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{alt}" '
        'style="width:100%;max-width:420px;display:block">' + "".join(parts) + "</svg>"
    )


def _short(d: date) -> str:
    return f"{d:%b} {d.day}"
