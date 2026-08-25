import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from driver import CPACDriver, DriverState


CPAC_SLOT = int(os.getenv("CPAC_SLOT", "1"))


class SetParametersRequest(BaseModel):
    target_temperature_c: float = Field(
        ...,
        description="Target plate temperature in °C",
    )


class CPACService:
    """
    Owns the single hardware driver instance.

    The API lock serializes operations so multiple HTTP requests
    cannot interleave command sequences on the same controller.
    """

    def __init__(self, slot: int):
        self.slot = slot
        self.driver = CPACDriver(slot=slot)
        self.lock = asyncio.Lock()

    async def initialize(self):
        async with self.lock:
            # Make initialize idempotent.
            if self.driver.state in (
                DriverState.READY,
                DriverState.RUNNING,
                DriverState.ABORTED,
            ):
                return {
                    "state": self.driver.state,
                    "slot": self.slot,
                    "already_initialized": True,
                }

            # If a previous initialization failed, rebuild the
            # transport before trying again.
            if self.driver.state == DriverState.ERROR:
                try:
                    await self.driver.box.stop()
                except Exception:
                    pass

                self.driver = CPACDriver(slot=self.slot)

            return await self.driver.initialize()

    async def close(self):
        try:
            await self.driver.box.stop()
        except Exception:
            pass


service = CPACService(slot=CPAC_SLOT)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # We deliberately do not initialize hardware automatically.
    # Scheduler/client explicitly calls /initialize.
    yield
    await service.close()


app = FastAPI(
    title="INHECO CPAC Driver",
    description=(
        "FastAPI device driver for an INHECO CPAC "
        "connected through an MTC/STC controller."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------


def translate_error(exc: Exception) -> HTTPException:
    message = str(exc)

    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=422,
            detail=message,
        )

    if "Timeout waiting for response" in message:
        return HTTPException(
            status_code=504,
            detail=message,
        )

    if (
        "not ready" in message.lower()
        or "not connected" in message.lower()
        or "aborted state" in message.lower()
    ):
        return HTTPException(
            status_code=409,
            detail=message,
        )

    return HTTPException(
        status_code=500,
        detail=message,
    )


# ---------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------


@app.get("/health")
async def health():
    state = service.driver.state

    healthy = state in (
        DriverState.READY,
        DriverState.RUNNING,
        DriverState.ABORTED,
    )

    return {
        "healthy": healthy,
        "state": state,
        "slot": service.slot,
        "last_error": service.driver.last_error,
    }


# ---------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------


@app.post("/initialize")
async def initialize():
    try:
        return await service.initialize()
    except Exception as exc:
        raise translate_error(exc)


# ---------------------------------------------------------------------
# Status / reads
# ---------------------------------------------------------------------


@app.get("/status")
async def get_status():
    try:
        async with service.lock:
            return await service.driver.get_status()
    except Exception as exc:
        raise translate_error(exc)


@app.get("/temperature")
async def get_actual_temperature():
    try:
        async with service.lock:
            temperature = await service.driver.get_actual_temperature()

        return {
            "actual_temperature_c": temperature,
        }

    except Exception as exc:
        raise translate_error(exc)


@app.get("/parameters")
async def get_parameters():
    try:
        async with service.lock:
            return await service.driver.get_parameters()
    except Exception as exc:
        raise translate_error(exc)


@app.get("/configuration")
async def get_configuration():
    """
    Configuration is intentionally read-only.

    Configuration writes were not exposed because external EEPROM
    writes were not sufficiently reliable on the installed firmware.
    """
    try:
        async with service.lock:
            return await service.driver.get_configuration()
    except Exception as exc:
        raise translate_error(exc)


# ---------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------


@app.put("/parameters")
async def set_parameters(request: SetParametersRequest):
    try:
        async with service.lock:
            return await service.driver.set_parameters(
                request.target_temperature_c
            )

    except Exception as exc:
        raise translate_error(exc)


# ---------------------------------------------------------------------
# Control
# ---------------------------------------------------------------------


@app.post("/start")
async def start():
    try:
        async with service.lock:
            return await service.driver.start()
    except Exception as exc:
        raise translate_error(exc)


@app.post("/stop")
async def stop():
    try:
        async with service.lock:
            return await service.driver.stop()
    except Exception as exc:
        raise translate_error(exc)


@app.post("/abort")
async def abort():
    try:
        async with service.lock:
            return await service.driver.abort()
    except Exception as exc:
        raise translate_error(exc)


@app.post("/reset")
async def reset():
    try:
        async with service.lock:
            return await service.driver.reset()
    except Exception as exc:
        raise translate_error(exc)