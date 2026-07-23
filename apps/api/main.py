from fastapi import FastAPI

app = FastAPI(title="SlideVision API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
