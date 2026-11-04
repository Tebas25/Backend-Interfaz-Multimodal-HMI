import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Sequence, Union

from app.models.cobot_menu_item import CobotMenuItem
from app.schemas.ws_messages import Screen

WAKE_WORDS = frozenset({"rony", "roni", "ronny", "ronnie", "ronni"})


# ---------- Acciones ----------


@dataclass(frozen=True)
class NavigateAction:
    screen: Screen


@dataclass(frozen=True)
class SelectDrinkAction:
    name: str


@dataclass(frozen=True)
class ShowIngredientsAction:
    name: str


@dataclass(frozen=True)
class CloseIngredientsAction:
    pass


VoiceAction = Union[
    NavigateAction, SelectDrinkAction, ShowIngredientsAction, CloseIngredientsAction
]


# ---------- Texto ----------


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", text)


def extract_command(text: str) -> str | None:
    tokens = normalize(text).split()
    if not any(t in WAKE_WORDS for t in tokens):
        return None
    return " ".join(t for t in tokens if t not in WAKE_WORDS)


def _norm_name(name: str) -> str:
    return " ".join(normalize(name).split())


def find_drink(command: str, items: Sequence[CobotMenuItem]) -> CobotMenuItem | None:
    tokens = command.split()
    padded = f" {' '.join(tokens)} "
    named = [(i, _norm_name(i.nombre_item)) for i in items]
    named = [(i, n) for i, n in named if n]

    exact = [
        (i, n) for i, n in named if f" {n} " in padded or n.replace(" ", "") in tokens
    ]
    if exact:
        return max(exact, key=lambda p: len(p[1]))[0]

    best, best_score = None, 0.0
    for item, name in named:
        size = len(name.split())
        for start in range(len(tokens) - size + 1):
            window = " ".join(tokens[start : start + size])
            score = SequenceMatcher(None, name, window).ratio()
            if score > best_score:
                best, best_score = item, score
    return best if best_score >= 0.8 else None


# ---------- Un handler por pantalla ----------

Handler = Callable[[str, Sequence[CobotMenuItem]], VoiceAction | None]

ORDER_WORDS = frozenset(
    {"tomar", "beber", "pedir", "ordenar", "bebida", "trago", "menu", "carta"}
)
INGREDIENT_WORDS = frozenset(
    {
        "ingredientes",
        "ingrediente",
        "lleva",
        "contiene",
        "tiene",
        "composicion",
        "hecho",
        "receta",
    }
)
CLOSE_WORDS = frozenset(
    {"cerrar", "cierra", "cierralo", "regresar", "regresa", "volver", "vuelve", "atras"}
)


def handle_welcome(command: str, items: Sequence[CobotMenuItem]) -> VoiceAction | None:
    if ORDER_WORDS & set(command.split()):
        return NavigateAction(Screen.MENU)
    return None


def handle_menu(command: str, items: Sequence[CobotMenuItem]) -> VoiceAction | None:
    words = set(command.split())

    if CLOSE_WORDS & words:
        return CloseIngredientsAction()

    drink = find_drink(command, items)
    if drink is None:
        return None
    if INGREDIENT_WORDS & words:
        return ShowIngredientsAction(drink.nombre_item)
    return SelectDrinkAction(drink.nombre_item)


HANDLERS: dict[Screen, Handler] = {
    Screen.WELCOME: handle_welcome,
    Screen.MENU: handle_menu,
}


def process_text(
    text: str, screen: Screen | None, items: Sequence[CobotMenuItem] = ()
) -> VoiceAction | None:
    command = extract_command(text)
    if not command:
        return None
    handler = HANDLERS.get(screen)
    return handler(command, items) if handler else None
