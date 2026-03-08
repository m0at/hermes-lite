"""Color scheme selection and theming for the CLI.

Two schemes: green/blue ("cyber") and pink/purple ("synthwave").
On first launch, user picks with a single left/right arrow keypress.
Choice is saved to config.yaml display.color_scheme.
"""

import sys
from typing import Optional

SCHEMES = {
    "cyber": {
        "primary": "#00FF88",
        "secondary": "#00BFFF",
        "accent": "#40E0D0",
        "dim": "#2E8B57",
        "border": "#00CED1",
        "text": "#E0FFF0",
        "logo_top": "#00FF88",
        "logo_mid": "#00BFFF",
        "logo_bot": "#40E0D0",
        "label": "green/blue",
        "emoji": "\033[32m\u2588\033[36m\u2588\033[0m",
    },
    "synthwave": {
        "primary": "#FF69B4",
        "secondary": "#BA55D3",
        "accent": "#DA70D6",
        "dim": "#8B4789",
        "border": "#FF69B4",
        "text": "#FFE4F0",
        "logo_top": "#FF69B4",
        "logo_mid": "#BA55D3",
        "logo_bot": "#DA70D6",
        "label": "pink/purple",
        "emoji": "\033[35m\u2588\033[95m\u2588\033[0m",
    },
}

DEFAULT_SCHEME = "cyber"


def get_scheme(name: Optional[str] = None) -> dict:
    """Get a color scheme by name, falling back to config then default."""
    if name and name in SCHEMES:
        return SCHEMES[name]

    from hermes_cli.config import load_config
    config = load_config()
    display = config.get("display", {})
    saved = display.get("color_scheme", "") if isinstance(display, dict) else ""
    if saved in SCHEMES:
        return SCHEMES[saved]
    return SCHEMES[DEFAULT_SCHEME]


def get_scheme_name() -> str:
    """Get the current scheme name from config."""
    from hermes_cli.config import load_config
    config = load_config()
    display = config.get("display", {})
    saved = display.get("color_scheme", "") if isinstance(display, dict) else ""
    return saved if saved in SCHEMES else DEFAULT_SCHEME


def pick_color_scheme() -> str:
    """Interactive single-keypress color scheme picker.

    Shows both options side by side. Left arrow = cyber, Right arrow = synthwave.
    Returns the chosen scheme name and saves it to config.
    """
    if not sys.stdin.isatty():
        return DEFAULT_SCHEME

    print()
    print(f"  {SCHEMES['cyber']['emoji']}  \033[1mgreen/blue\033[0m     or     \033[1mpink/purple\033[0m  {SCHEMES['synthwave']['emoji']}")
    print()
    print("       \033[2m← left                right →\033[0m")
    print()

    import tty
    import termios

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[D":  # left arrow
                    choice = "cyber"
                    break
                elif seq == "[C":  # right arrow
                    choice = "synthwave"
                    break
            elif ch in ("q", "\x03"):  # q or ctrl-c
                choice = DEFAULT_SCHEME
                break
            elif ch == "\r" or ch == "\n":
                choice = DEFAULT_SCHEME
                break
    except Exception:
        choice = DEFAULT_SCHEME
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    # Save to config
    from hermes_cli.config import load_config, save_config
    config = load_config()
    if not isinstance(config.get("display"), dict):
        config["display"] = {}
    config["display"]["color_scheme"] = choice
    save_config(config)

    label = SCHEMES[choice]["label"]
    print(f"\r  \033[1m{label}\033[0m it is.\033[K")
    print()
    return choice


def needs_scheme_pick() -> bool:
    """Check if user hasn't picked a color scheme yet."""
    from hermes_cli.config import load_config
    config = load_config()
    display = config.get("display", {})
    if not isinstance(display, dict):
        return True
    return "color_scheme" not in display
