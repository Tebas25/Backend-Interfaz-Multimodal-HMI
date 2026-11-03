import re
import unicodedata
from dataclasses import dataclass
from typing import Callable

from app.schemas.ws_messages import Screen

WAKE_WORDS = frozenset({"rony", "roni", "ronny", "ronnie", "ronni"})


@dataclass(frozen=True)
class NavigateAction:
    screen: Screen


# Cuando haya más acciones (elegir bebida, confirmar...): Union[NavigateAction, SelectDrinkAction, ...]
VoiceAction = NavigateAction


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", text)


def extract_command(text: str) -> str | None:
    tokens = normalize(text).split()
    if not any(t in WAKE_WORDS for t in tokens):
        return None
    return " ".join(t for t in tokens if t not in WAKE_WORDS)


# ---------- Un handler por pantalla ----------

Handler = Callable[[str], VoiceAction | None]

ORDER_WORDS = frozenset(
    {"tomar", "beber", "pedir", "ordenar", "bebida", "trago", "menu", "carta"}
)


def handle_welcome(command: str) -> VoiceAction | None:
    if ORDER_WORDS & set(command.split()):
        return NavigateAction(Screen.MENU)
    return None


def handle_menu(command: str) -> VoiceAction | None:
    # TODO: elegir bebida por nombre, confirmar, cancelar/volver...
    return None


HANDLERS: dict[Screen, Handler] = {
    Screen.WELCOME: handle_welcome,
    Screen.MENU: handle_menu,
}


def process_text(text: str, screen: Screen | None) -> VoiceAction | None:
    command = extract_command(text)
    if not command:
        return None
    handler = HANDLERS.get(screen)
    return handler(command) if handler else None
