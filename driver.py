import asyncio
from enum import Enum
from pylabrobot.inheco.control_box import InhecoTECControlBox # type: ignore

class DriverState(str, Enum):
    DISCONNECTED = "disconnected"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    ERROR = "error"

class CPACMode(str, Enum):
    HEATING = "heating"
    COOLING = "cooling"
    OFF = "off"

CPAC_MODE_MAP = {
    0: CPACMode.HEATING,
    1: CPACMode.COOLING,
    2: CPACMode.OFF,
}

class CPACDriver:
    def __init__(self, slot: int):
        if slot not in range(1, 7):
            raise ValueError("Slot must be between 1 and 6")
         
        self.slot = slot
        self.box = InhecoTECControlBox()
        self.lock = asyncio.Lock()

        self.state = DriverState.DISCONNECTED

        self.controller_firmware = None
        self.slot_firmware = None
        self.article_number = None
        self.device_type = None
        self.min_temperature = None
        self.max_temperature = None
        self.last_error = None
        self.controller_type = None

    async def _send(self, command: str):
        async with self.lock:
            response = await self.box.send_command(command)
            await asyncio.sleep(0.1)
            return response

    def _ensure_ready(self):
        if self.state in (
            DriverState.DISCONNECTED,
            DriverState.INITIALIZING,
            DriverState.ERROR,
        ):
            raise RuntimeError(
                f"Driver is not ready for commands (state={self.state.value})"
            )

    async def _read_mode(self):
        mode_raw = int(
                await self._send(f"{self.slot}RHE")
            )
        try:
            mode = CPAC_MODE_MAP[mode_raw]
        except KeyError:
            raise RuntimeError(f"Unknown CPAC mode: {mode_raw}")
        return mode
    
    async def initialize(self):
        self.state = DriverState.INITIALIZING

        try: 
            await self.box.setup()

            # First command may report expected reset code 6.
            try:
                self.controller_firmware = await self._send("0RFV1")
            except RuntimeError as exc:
                if "0rfv6" not in str(exc).lower():
                    raise
                else:
                    # Try again
                    await asyncio.sleep(0.2)
                    self.controller_firmware = await self._send("0RFV1")

            # Verify controller
            controller_type = int(await self._send("0RTD0"))
            if controller_type not in (0, 1, 255):
                raise RuntimeError(
                    f"Unexpected controller type: {controller_type}"
                )
            self.controller_type = controller_type

            # Verify something is connected to the configured slot.
            self.article_number = await self._send(
                f"0RAN{self.slot}"
            )

            # Verify it is a CPAC.
            self.device_type = int(
                await self._send(f"0RTD{self.slot}")
            )
            if self.device_type not in (1, 4):
                raise RuntimeError(
                    f"Slot {self.slot} is not a CPAC "
                    f"(device type={self.device_type})"
                )

            # Device information.
            self.slot_firmware = await self._send(
                f"{self.slot}RFV1"
            )

            self.min_temperature = (
                int(await self._send(f"{self.slot}RLT")) / 10
            )

            self.max_temperature = (
                int(await self._send(f"{self.slot}RMT1")) / 10
            )

            actual_temperature = (
                int(await self._send(f"{self.slot}RAT")) / 10
            )

            mode = await self._read_mode()

            errors = await self._send(
                f"{self.slot}REC"
            )

            # Do not alter existing hardware state.
            if mode == CPACMode.OFF:
                self.state = DriverState.READY
            else:
                self.state = DriverState.RUNNING

            return {
                "state": self.state,
                "slot": self.slot,
                "controller_firmware": self.controller_firmware,
                "slot_firmware": self.slot_firmware,
                "article_number": self.article_number,
                "device_type": self.device_type,
                "actual_temperature_c": actual_temperature,
                "min_temperature_c": self.min_temperature,
                "max_temperature_c": self.max_temperature,
                "mode": mode,
                "errors": errors,
            }

        except Exception as exc:
            self.state = DriverState.ERROR
            self.last_error = str(exc)
            raise

    async def get_actual_temperature(self) -> float:
        self._ensure_ready()

        raw = await self._send(f"{self.slot}RAT")
        return int(raw) / 10

    async def get_status(self):
        self._ensure_ready()

        actual_temperature = (
            int(await self._send(f"{self.slot}RAT")) / 10
        )

        mode_raw = int(
            await self._send(f"{self.slot}RHE")
        )

        try:
            mode = CPAC_MODE_MAP[mode_raw]
        except KeyError:
            raise RuntimeError(f"Unknown CPAC mode: {mode_raw}")

        errors = await self._send(
            f"{self.slot}REC"
        )

        if mode == CPACMode.OFF:
            self.state = DriverState.READY
        else:
            self.state = DriverState.RUNNING

        return {
            "state": self.state,
            "slot": self.slot,
            "actual_temperature_c": actual_temperature,
            "mode": mode,
            "errors": errors,
        }

    async def get_parameters(self):
        ...

    async def set_parameters(self, params):
        ...

    async def stop(self):
        ...

    async def reset(self):
        ...

    async def abort(self):
        ...
