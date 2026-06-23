"""`demoreel check --live` — open the page, replay the flow, and verify every selector
the spec references actually resolves before the (slow) full render.

Selectors are checked in the page state they'll be used in: each scene's action advances
the page, and annotation/wait_for selectors are checked after the action runs.
"""

from __future__ import annotations

from dataclasses import dataclass

from .capture import _resolve_url
from .spec import Arrow, Callout, DemoSpec, Scene, TypeAction


@dataclass
class CheckRow:
    scene: int
    selector: str
    ok: bool
    note: str = ""


def check_live(spec: DemoSpec) -> list[CheckRow]:
    from playwright.sync_api import sync_playwright

    rows: list[CheckRow] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=spec.headless)
        ctx_kwargs: dict = {"viewport": {"width": spec.viewport[0], "height": spec.viewport[1]}}
        if spec.storage_state:
            ctx_kwargs["storage_state"] = spec.storage_state
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        try:
            for i, scene in enumerate(spec.scenes):
                _check_scene(page, spec, scene, i, rows)
        finally:
            context.close()
            browser.close()
    return rows


def _check_scene(page, spec: DemoSpec, scene: Scene, i: int, rows: list[CheckRow]) -> None:
    act = scene.primary_action()
    if act:
        kind, val = act
        sel = _action_selector(kind, val)
        if sel:
            rows.append(_probe(page, i, sel))
        _advance(page, spec, kind, val)
    for sel in _post_selectors(scene):
        rows.append(_probe(page, i, sel))


def _probe(page, scene: int, selector: str) -> CheckRow:
    try:
        page.locator(selector).first.wait_for(state="attached", timeout=4000)
        return CheckRow(scene, selector, True)
    except Exception as exc:  # noqa: BLE001
        return CheckRow(scene, selector, False, type(exc).__name__)


def _advance(page, spec: DemoSpec, kind: str, val) -> None:
    try:
        if kind == "goto":
            page.goto(_resolve_url(spec.url, str(val)), wait_until="domcontentloaded")
            page.wait_for_timeout(300)
        elif kind == "click":
            page.locator(str(val)).first.click(timeout=6000)
        elif kind == "type":
            ta = val if isinstance(val, TypeAction) else TypeAction(text=str(val))
            if ta.selector:
                page.locator(ta.selector).first.click(timeout=6000)
            page.keyboard.type(ta.text, delay=0)
        elif kind == "press":
            page.keyboard.press(str(val))
        elif kind == "scroll" and val.to:
            page.locator(val.to).first.scroll_into_view_if_needed()
        elif kind == "wait":
            page.wait_for_timeout(int(float(val) * 1000))
        page.wait_for_timeout(150)
    except Exception:  # noqa: BLE001 - a broken selector is reported, not raised
        pass


def _action_selector(kind: str, val) -> str | None:
    if kind in ("click", "hover"):
        return str(val)
    if kind == "type" and isinstance(val, TypeAction):
        return val.selector
    if kind == "scroll" and val.to:
        return val.to
    return None


def _post_selectors(scene: Scene) -> list[str]:
    out: list[str] = []
    for f in ("highlight", "spotlight", "focus", "wait_for"):
        v = getattr(scene, f)
        if v:
            out.append(v)
    if isinstance(scene.callout, Callout) and scene.callout.at:
        out.append(scene.callout.at)
    if isinstance(scene.arrow, Arrow):
        out.append(scene.arrow.to)
    return out
