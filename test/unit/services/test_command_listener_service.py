import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest
import speech_recognition as sr

from app.schemas.ws_messages import Screen
from app.services import command_listener_service
from app.services.command_listener_service import CommandListenerService
from app.services.command_processor import NavigateAction
from app.services.screen_state import ScreenState


async def esperar_hasta(condicion, timeout=3.0):
    limite = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < limite:
        if condicion():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.fixture
def on_action():
    return AsyncMock(name="on_action")


@pytest.fixture
async def listener(microfono_falso, on_action):
    servicio = CommandListenerService(on_action=on_action)
    yield servicio
    await servicio.stop()


# ---------- constructor ----------


def test_valores_por_defecto(on_action):
    servicio = CommandListenerService(on_action=on_action)

    assert servicio._on_action is on_action
    assert servicio._language == "es-EC"
    assert servicio._phrase_time_limit == 6.0
    assert servicio._get_items() == ()


def test_acepta_idioma_y_limite_de_frase_personalizados(on_action):
    servicio = CommandListenerService(
        on_action, language="en-US", phrase_time_limit=3.5
    )

    assert servicio._language == "en-US"
    assert servicio._phrase_time_limit == 3.5


def test_estado_inicial_sin_hilo_ni_tarea(on_action):
    servicio = CommandListenerService(on_action=on_action)

    assert servicio._loop is None
    assert servicio._stop_listening is None
    assert servicio._task is None
    assert servicio._queue.maxsize == 5
    assert servicio._queue.empty()


def test_crea_un_reconocedor_de_speech_recognition(on_action):
    servicio = CommandListenerService(on_action=on_action)

    assert isinstance(servicio._recognizer, sr.Recognizer)


def test_el_constructor_no_toca_el_microfono(on_action):
    CommandListenerService(on_action=on_action)


# ---------- start ----------


async def test_start_con_microfono_devuelve_true(listener):
    assert await listener.start() is True


async def test_start_guarda_el_bucle_de_eventos_actual(listener):
    await listener.start()

    assert listener._loop is asyncio.get_running_loop()


async def test_start_crea_la_tarea_de_reconocimiento(listener):
    await listener.start()

    assert listener._task is not None
    assert listener._task.get_name() == "command-listener"
    assert not listener._task.done()


async def test_start_imprime_que_esta_escuchando(listener, capsys):
    await listener.start()

    assert "[Voz] Escuchando..." in capsys.readouterr().out


async def test_start_calibra_el_ruido_ambiente_durante_un_segundo(
    listener, microfono_falso
):
    await listener.start()

    assert microfono_falso.ambient_calls == [("fuente-de-audio", 1)]


async def test_start_escucha_en_segundo_plano_con_el_limite_de_frase(
    microfono_falso, on_action
):
    servicio = CommandListenerService(on_action=on_action, phrase_time_limit=4.5)

    await servicio.start()

    try:
        assert len(microfono_falso.background_calls) == 1
        assert microfono_falso.background_calls[0][1] == 4.5
    finally:
        await servicio.stop()


async def test_start_registra_on_audio_como_callback_de_audio(
    listener, microfono_falso
):
    await listener.start()

    assert microfono_falso.background_callback == listener._on_audio


async def test_start_guarda_la_funcion_para_detener_la_escucha(
    listener, microfono_falso
):
    await listener.start()

    assert listener._stop_listening is microfono_falso.stop_listening


async def test_start_abre_el_microfono_fuera_del_hilo_del_bucle(
    listener, microfono_falso
):
    await listener.start()

    assert microfono_falso.threads["ambient"] is not threading.current_thread()


async def test_start_sin_microfono_devuelve_false_e_informa(on_action, capsys):
    servicio = CommandListenerService(on_action=on_action)

    resultado = await servicio.start()

    assert resultado is False
    assert (
        "[Voz] Control por voz deshabilitado: OSError: Micrófono deshabilitado"
        in capsys.readouterr().out
    )
    assert servicio._task is None
    assert servicio._stop_listening is None


async def test_start_sin_pyaudio_devuelve_false(monkeypatch, on_action, capsys):
    def sin_pyaudio(*args, **kwargs):
        raise AttributeError("Could not find PyAudio; check installation")

    monkeypatch.setattr(sr, "Microphone", sin_pyaudio)
    servicio = CommandListenerService(on_action=on_action)

    resultado = await servicio.start()

    assert resultado is False
    assert "AttributeError" in capsys.readouterr().out
    assert servicio._task is None


async def test_start_si_falla_la_calibracion_devuelve_false_y_no_escucha(
    listener, microfono_falso
):
    def falla(source, duration=1):
        raise OSError("dispositivo ocupado")

    microfono_falso.adjust_for_ambient_noise = falla

    resultado = await listener.start()

    assert resultado is False
    assert microfono_falso.background_calls == []
    assert listener._task is None


# ---------- stop ----------


async def test_stop_sin_haber_iniciado_no_hace_nada(on_action):
    servicio = CommandListenerService(on_action=on_action)

    await servicio.stop()


async def test_stop_despues_de_un_start_fallido_no_hace_nada(on_action):
    servicio = CommandListenerService(on_action=on_action)
    await servicio.start()

    await servicio.stop()


async def test_stop_detiene_la_escucha_sin_esperar_al_hilo(listener, microfono_falso):
    await listener.start()

    await listener.stop()

    microfono_falso.stop_listening.assert_called_once_with(wait_for_stop=False)


async def test_stop_cancela_la_tarea_de_reconocimiento(listener):
    await listener.start()
    tarea = listener._task

    await listener.stop()

    assert tarea.cancelled()


async def test_stop_se_puede_llamar_dos_veces(listener):
    await listener.start()

    await listener.stop()
    await listener.stop()


# ---------- _on_audio / _enqueue ----------


async def test_on_audio_sin_bucle_descarta_el_audio(on_action):
    servicio = CommandListenerService(on_action=on_action)

    servicio._on_audio(None, "audio-1")

    assert servicio._queue.empty()


async def test_on_audio_desde_otro_hilo_encola_el_audio_en_el_bucle(on_action):
    servicio = CommandListenerService(on_action=on_action)
    servicio._loop = asyncio.get_running_loop()

    await asyncio.to_thread(
        servicio._on_audio, None, "audio-1"
    )
    llego = await esperar_hasta(lambda: not servicio._queue.empty())

    assert llego
    assert servicio._queue.get_nowait() == "audio-1"


async def test_enqueue_guarda_el_audio(on_action):
    servicio = CommandListenerService(on_action=on_action)

    servicio._enqueue("audio-1")

    assert servicio._queue.qsize() == 1


async def test_enqueue_con_la_cola_llena_descarta_el_audio_nuevo(on_action, capsys):
    servicio = CommandListenerService(on_action=on_action)
    for i in range(5):
        servicio._enqueue(f"audio-{i}")

    servicio._enqueue("audio-extra")  # no debe lanzar

    assert "[Voz] Cola llena, se descarta un audio" in capsys.readouterr().out
    assert [servicio._queue.get_nowait() for _ in range(5)] == [
        f"audio-{i}" for i in range(5)
    ]


# ---------- _run ----------


@pytest.fixture
async def run_task(listener):
    """Arranca el bucle de reconocimiento (_run) aislado, con handle_text simulado."""
    listener.handle_text = AsyncMock()
    tarea = asyncio.create_task(listener._run())
    yield tarea
    tarea.cancel()
    try:
        await tarea
    except asyncio.CancelledError:
        pass


async def test_run_reconoce_el_audio_y_entrega_el_texto(
    listener, microfono_falso, run_task
):
    microfono_falso.results["a1"] = "Rony quiero tomar algo"

    listener._queue.put_nowait("a1")
    await esperar_hasta(lambda: listener.handle_text.await_count == 1)

    listener.handle_text.assert_awaited_once_with("Rony quiero tomar algo")


async def test_run_usa_el_idioma_configurado(microfono_falso, on_action):
    servicio = CommandListenerService(on_action=on_action, language="en-US")
    servicio.handle_text = AsyncMock()
    microfono_falso.results["a1"] = "hello"
    tarea = asyncio.create_task(servicio._run())

    servicio._queue.put_nowait("a1")
    await esperar_hasta(lambda: servicio.handle_text.await_count == 1)
    tarea.cancel()

    assert microfono_falso.recognize_calls == [("a1", "en-US")]


async def test_run_procesa_los_audios_en_orden(listener, microfono_falso, run_task):
    microfono_falso.results.update({"a1": "uno", "a2": "dos", "a3": "tres"})

    for audio in ("a1", "a2", "a3"):
        listener._queue.put_nowait(audio)
    await esperar_hasta(lambda: listener.handle_text.await_count == 3)

    assert [c.args[0] for c in listener.handle_text.await_args_list] == [
        "uno",
        "dos",
        "tres",
    ]


async def test_run_reconoce_en_un_hilo_aparte_para_no_bloquear_el_bucle(
    listener, microfono_falso, run_task
):
    microfono_falso.results["a1"] = "hola"

    listener._queue.put_nowait("a1")
    await esperar_hasta(lambda: listener.handle_text.await_count == 1)

    assert microfono_falso.threads["recognize"] is not threading.current_thread()


async def test_run_si_no_se_entiende_el_audio_lo_ignora_y_sigue(
    listener, microfono_falso, run_task
):
    microfono_falso.results["a1"] = sr.UnknownValueError()
    microfono_falso.results["a2"] = "Rony menu"

    listener._queue.put_nowait("a1")
    listener._queue.put_nowait("a2")
    await esperar_hasta(lambda: listener.handle_text.await_count == 1)

    listener.handle_text.assert_awaited_once_with("Rony menu")


async def test_run_si_falla_el_servicio_de_reconocimiento_lo_informa_y_sigue(
    listener, microfono_falso, run_task, capsys
):
    microfono_falso.results["a1"] = sr.RequestError("sin internet")
    microfono_falso.results["a2"] = "Rony menu"

    listener._queue.put_nowait("a1")
    listener._queue.put_nowait("a2")
    await esperar_hasta(lambda: listener.handle_text.await_count == 1)

    assert (
        "[Voz] Error del servicio de reconocimiento: sin internet"
        in capsys.readouterr().out
    )
    listener.handle_text.assert_awaited_once_with("Rony menu")


async def test_run_ante_un_error_inesperado_lo_informa_y_sigue(
    listener, microfono_falso, run_task, capsys
):
    microfono_falso.results["a1"] = ValueError("boom")
    microfono_falso.results["a2"] = "Rony menu"

    listener._queue.put_nowait("a1")
    listener._queue.put_nowait("a2")
    await esperar_hasta(lambda: listener.handle_text.await_count == 1)

    assert "[Voz] Error inesperado: ValueError: boom" in capsys.readouterr().out
    listener.handle_text.assert_awaited_once_with("Rony menu")


async def test_run_espera_en_silencio_mientras_no_hay_audio(
    listener, microfono_falso, run_task
):
    await asyncio.sleep(0.05)

    assert not run_task.done()
    assert microfono_falso.recognize_calls == []
    listener.handle_text.assert_not_awaited()


# ---------- handle_text ----------


async def test_handle_text_imprime_lo_que_escucho(on_action, capsys):
    servicio = CommandListenerService(on_action=on_action)

    await servicio.handle_text("hola mundo")

    assert "[Voz] Escuché: 'hola mundo'" in capsys.readouterr().out


async def test_handle_text_desde_welcome_con_orden_ejecuta_la_accion_de_navegar(
    on_action, capsys
):
    ScreenState.current = Screen.WELCOME
    servicio = CommandListenerService(on_action=on_action)

    await servicio.handle_text("Rony quiero tomar algo")

    on_action.assert_awaited_once_with(NavigateAction(Screen.MENU))
    assert "[Voz] Acción: NavigateAction" in capsys.readouterr().out


@pytest.mark.parametrize("texto", ["quiero tomar algo", "Rony", "Rony hola", ""])
async def test_handle_text_sin_palabra_clave_o_sin_orden_no_ejecuta_nada(
    on_action, capsys, texto
):
    ScreenState.current = Screen.WELCOME
    servicio = CommandListenerService(on_action=on_action)

    await servicio.handle_text(texto)

    on_action.assert_not_awaited()
    assert "[Voz] Acción" not in capsys.readouterr().out


async def test_handle_text_desde_menu_no_ejecuta_nada(on_action):
    ScreenState.current = Screen.MENU
    servicio = CommandListenerService(on_action=on_action)

    await servicio.handle_text("Rony quiero tomar algo")

    on_action.assert_not_awaited()


async def test_handle_text_sin_pantalla_conocida_no_ejecuta_nada(on_action):
    assert ScreenState.current is None
    servicio = CommandListenerService(on_action=on_action)

    await servicio.handle_text("Rony quiero tomar algo")

    on_action.assert_not_awaited()


async def test_handle_text_usa_la_pantalla_actual_en_el_momento_de_escuchar(on_action):
    servicio = CommandListenerService(on_action=on_action)

    ScreenState.current = Screen.WELCOME
    await servicio.handle_text("Rony quiero tomar algo")
    ScreenState.current = Screen.MENU
    await servicio.handle_text("Rony quiero tomar algo")

    assert on_action.await_count == 1


async def test_handle_text_entrega_el_texto_y_la_pantalla_a_process_text(
    monkeypatch, on_action
):
    process = MagicMock(return_value=None)
    monkeypatch.setattr(command_listener_service, "process_text", process)
    ScreenState.current = Screen.MENU
    servicio = CommandListenerService(on_action=on_action)

    await servicio.handle_text("algo que dijo")

    process.assert_called_once_with("algo que dijo", Screen.MENU, ())


async def test_handle_text_ejecuta_la_accion_que_devuelve_process_text(
    monkeypatch, on_action
):
    accion = NavigateAction(Screen.WELCOME)
    monkeypatch.setattr(
        command_listener_service, "process_text", lambda texto, pantalla, items: accion
    )
    servicio = CommandListenerService(on_action=on_action)

    await servicio.handle_text("lo que sea")

    on_action.assert_awaited_once_with(accion)


async def test_handle_text_si_la_accion_falla_no_propaga_el_error_y_lo_informa(capsys):
    ScreenState.current = Screen.WELCOME
    servicio = CommandListenerService(
        on_action=AsyncMock(side_effect=RuntimeError("falla"))
    )

    await servicio.handle_text("Rony quiero tomar algo")  # no debe lanzar

    assert (
        "[Voz] Error ejecutando la acción: RuntimeError: falla"
        in capsys.readouterr().out
    )


# ---------- bebidas disponibles (get_items) ----------


async def test_handle_text_entrega_las_bebidas_actuales_a_process_text(
    monkeypatch, on_action
):
    bebidas = [object(), object()]
    process = MagicMock(return_value=None)
    monkeypatch.setattr(command_listener_service, "process_text", process)
    ScreenState.current = Screen.MENU
    servicio = CommandListenerService(on_action=on_action, get_items=lambda: bebidas)

    await servicio.handle_text("Rony un mojito")

    process.assert_called_once_with("Rony un mojito", Screen.MENU, bebidas)


async def test_handle_text_consulta_las_bebidas_en_cada_frase(monkeypatch, on_action):
    process = MagicMock(return_value=None)
    monkeypatch.setattr(command_listener_service, "process_text", process)
    catalogo = [1]
    servicio = CommandListenerService(on_action=on_action, get_items=lambda: catalogo)

    await servicio.handle_text("primera")
    catalogo = [1, 2]
    await servicio.handle_text("segunda")

    assert process.call_args_list[0].args[2] == [1]
    assert process.call_args_list[1].args[2] == [1, 2]


async def test_handle_text_con_bebidas_reales_selecciona_la_nombrada(on_action):
    from decimal import Decimal

    from app.models.cobot_menu_item import CobotMenuItem
    from app.services.command_processor import SelectDrinkAction

    mojito = CobotMenuItem(
        nombre_item="Mojito",
        ingredientes=None,
        imagen=None,
        codigo_modbus=1,
        estado=True,
        precio_item=Decimal("5.50"),
    )
    ScreenState.current = Screen.MENU
    servicio = CommandListenerService(on_action=on_action, get_items=lambda: [mojito])

    await servicio.handle_text("Rony quiero un mojito")

    on_action.assert_awaited_once_with(SelectDrinkAction("Mojito"))