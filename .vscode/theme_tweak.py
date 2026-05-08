import colorsys
import json
from pathlib import Path


HUE = 20.0
SATURATION = 0.62
LIGHTNESS = 0.20


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def normalize_hue(value: float) -> float:
    return value % 360.0


def hex_from_hsl(hue: float, saturation: float, lightness: float) -> str:
    h = normalize_hue(hue) / 360.0
    l = clamp_unit(lightness)
    s = clamp_unit(saturation)
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))


def mix(base: float, amount: float) -> float:
    return clamp_unit(base + amount)


settings = {
    "workbench.colorTheme": "Default Dark Modern",
    "workbench.preferredDarkColorTheme": "Default Dark Modern",
    "workbench.colorCustomizations": {
        "editor.background": hex_from_hsl(HUE, SATURATION * 0.45, mix(LIGHTNESS, -0.09)),
        "editorGroupHeader.tabsBackground": hex_from_hsl(HUE, SATURATION * 0.42, mix(LIGHTNESS, -0.11)),
        "editorGroupHeader.tabsBorder": hex_from_hsl(HUE, SATURATION * 0.78, mix(LIGHTNESS, 0.04)),
        "sideBar.background": hex_from_hsl(HUE, SATURATION * 0.48, mix(LIGHTNESS, -0.14)),
        "sideBar.border": hex_from_hsl(HUE, SATURATION * 0.78, mix(LIGHTNESS, 0.04)),
        "activityBar.background": hex_from_hsl(HUE, SATURATION * 0.58, mix(LIGHTNESS, -0.08)),
        "activityBar.foreground": hex_from_hsl(HUE, SATURATION * 0.90, mix(LIGHTNESS, 0.54)),
        "activityBar.activeBorder": hex_from_hsl(HUE, 0.92, mix(LIGHTNESS, 0.42)),
        "titleBar.activeBackground": hex_from_hsl(HUE, SATURATION * 0.82, LIGHTNESS),
        "titleBar.activeForeground": "#F4FBFF",
        "titleBar.inactiveBackground": hex_from_hsl(HUE, SATURATION * 0.60, mix(LIGHTNESS, -0.04)),
        "titleBar.inactiveForeground": hex_from_hsl(HUE, SATURATION * 0.50, mix(LIGHTNESS, 0.56)),
        "statusBar.background": hex_from_hsl(HUE, SATURATION * 0.84, mix(LIGHTNESS, -0.01)),
        "statusBar.foreground": "#F4FBFF",
        "statusBar.debuggingBackground": hex_from_hsl(HUE + 8.0, SATURATION * 0.90, mix(LIGHTNESS, 0.06)),
        "statusBar.debuggingForeground": "#F4FBFF",
        "tab.activeBackground": hex_from_hsl(HUE, SATURATION * 0.56, mix(LIGHTNESS, -0.06)),
        "tab.inactiveBackground": hex_from_hsl(HUE, SATURATION * 0.34, mix(LIGHTNESS, -0.11)),
        "tab.activeBorderTop": hex_from_hsl(HUE, 0.92, mix(LIGHTNESS, 0.42)),
        "list.activeSelectionBackground": hex_from_hsl(HUE, SATURATION * 0.72, LIGHTNESS),
        "list.inactiveSelectionBackground": hex_from_hsl(HUE, SATURATION * 0.52, mix(LIGHTNESS, -0.04)),
        "list.hoverBackground": hex_from_hsl(HUE, SATURATION * 0.54, mix(LIGHTNESS, -0.02)),
        "editorLineNumber.activeForeground": hex_from_hsl(HUE, 0.95, mix(LIGHTNESS, 0.52)),
        "editorCursor.foreground": hex_from_hsl(HUE, 0.95, mix(LIGHTNESS, 0.54)),
        "focusBorder": hex_from_hsl(HUE, 0.95, mix(LIGHTNESS, 0.46)),
        "panel.border": hex_from_hsl(HUE, SATURATION * 0.78, mix(LIGHTNESS, 0.04)),
    },
}


settings_path = Path(__file__).with_name("settings.json")
settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

print(f"Wrote {settings_path} with hue={HUE}, saturation={SATURATION}, lightness={LIGHTNESS}")
