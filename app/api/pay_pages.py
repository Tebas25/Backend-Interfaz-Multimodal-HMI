from html import escape
from string import Template

from fastapi import APIRouter, Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services.payment_service import PaymentSession, PaymentStatus

router = APIRouter()

PAYMENT_ID = Path(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
NO_STORE = {"Cache-Control": "no-store"}

_PAGE = Template(
    """<!doctype html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pago · Rony</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#000;font-family:system-ui,"Segoe UI",Roboto,sans-serif;padding:16px}
  .card{width:100%;max-width:420px;background:#D9D9D9;border-radius:24px;padding:28px 24px;text-align:center}
  h1{margin:0 0 6px;font-size:28px}
  .price{font-size:26px;font-weight:700;color:#A66F33;margin:0 0 24px}
  p{font-size:18px;margin:0 0 8px}
  form{margin:0 0 12px}
  button{width:100%;min-height:56px;border:0;border-radius:10px;font-size:20px;
         font-weight:700;color:#F3E9DC;background:#A66F33}
  button.reject{background:#D4553A}
  small{display:block;margin-top:16px;color:#555}
</style></head>
<body><main class="card">$body<small>Demostración: no se realiza ningún cobro real.</small></main></body></html>"""
)

_FINAL = {
    PaymentStatus.APPROVED: (
        "¡Pago realizado!",
        "Ya puedes volver a la pantalla de Rony.",
    ),
    PaymentStatus.REJECTED: ("Pago rechazado", "No se realizó ningún cobro."),
    PaymentStatus.EXPIRED: (
        "Código expirado",
        "Genera uno nuevo desde la pantalla de Rony.",
    ),
    PaymentStatus.CANCELLED: (
        "Pedido cancelado",
        "Este pedido se canceló en la pantalla de Rony.",
    ),
}


def _page(body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        _PAGE.substitute(body=body), status_code=status_code, headers=NO_STORE
    )


def _render(session: PaymentSession) -> HTMLResponse:
    status = session.effective_status
    if status is PaymentStatus.PENDING:
        pid = escape(session.id)
        return _page(
            f"<h1>{escape(session.drink.nombre_item)}</h1>"
            f'<div class="price">${session.price:.2f}</div>'
            f'<form method="post" action="/pay/{pid}/approve"><button>Realizar pago</button></form>'
            f'<form method="post" action="/pay/{pid}/reject"><button class="reject">Rechazar pago</button></form>'
        )
    title, text = _FINAL[status]
    return _page(f"<h1>{title}</h1><p>{text}</p>")


@router.get("/pay/{payment_id}", response_class=HTMLResponse)
async def pay_page(request: Request, payment_id: str = PAYMENT_ID):
    session = request.app.state.payment_service.get(payment_id)
    if session is None:
        return _page(
            "<h1>Enlace no válido</h1><p>Este código no existe o ya no está disponible.</p>",
            404,
        )
    return _render(session)


@router.post("/pay/{payment_id}/approve")
async def approve(request: Request, payment_id: str = PAYMENT_ID):
    await request.app.state.payment_service.approve(payment_id)
    return RedirectResponse(f"/pay/{payment_id}", status_code=303)


@router.post("/pay/{payment_id}/reject")
async def reject(request: Request, payment_id: str = PAYMENT_ID):
    await request.app.state.payment_service.reject(payment_id)
    return RedirectResponse(f"/pay/{payment_id}", status_code=303)
