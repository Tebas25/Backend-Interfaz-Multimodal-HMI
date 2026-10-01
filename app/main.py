from fastapi import FastAPI

app = FastAPI(
    title="API Bartender Robótico - Módulo Multimodal",
    description="Estructura base de la API local.",
    version="1.0.0",
)


@app.get("/")
async def root():
    return {"status": "ok", "message": "Estructura base configurada y en línea."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
