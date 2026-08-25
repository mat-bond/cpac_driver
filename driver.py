import asyncio
from enum import Enum
from pylabrobot.inheco.control_box import InhecoTECControlBox # type: ignore

class DriverState(str, Enum):
    DISCONNECTED = "disconnected"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    ERROR = "error"
    ABORTED = "aborted"

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
            #print(f">> {command}")

            try:
                response = await asyncio.wait_for(
                    self.box.send_command(command),
                    timeout=2.0,
                )

                #print(f"<< {response}")
                return response

            except asyncio.TimeoutError:
                print(f"!! timeout: {command}")
                raise RuntimeError(
                    f"Timeout waiting for response to {command}"
                )

            finally:
                await asyncio.sleep(0.1)

    def _ensure_ready(self):
        if self.state in (
            DriverState.DISCONNECTED,
            DriverState.INITIALIZING,
            DriverState.ERROR,
        ):
            raise RuntimeError(
                f"Driver is not ready for commands (state={self.state.value})"
            )
        if self.state == DriverState.ABORTED:
            self._manage_aborted_state()

    def _ensure_connected(self):
        if self.state in (
            DriverState.DISCONNECTED,
            DriverState.INITIALIZING,
        ):
            raise RuntimeError(
                f"Driver is not connected "
                f"(state={self.state.value})"
            )
    

    async def _read_mode(self) -> CPACMode:
        mode_raw = int(
                await self._send(f"{self.slot}RHE")
            )
        try:
            mode = CPAC_MODE_MAP[mode_raw]
        except KeyError:
            raise RuntimeError(f"Unknown CPAC mode: {mode_raw}")
        return mode

    def _manage_aborted_state(self):
        # TODO: Manage aborted state
        raise RuntimeError(
        "Driver is in aborted state. Reset is required before continuing."
    )

    async def _set_pid(
        self,
        selector: int,
        pid: dict,
    ):
        allowed = {"p", "i", "d"}

        unknown = set(pid) - allowed
        if unknown:
            raise ValueError(
                f"Unknown PID parameters: {unknown}"
            )

        for name, value in pid.items():
            if not isinstance(value, int):
                raise ValueError(
                    f"PID {name.upper()} must be an integer"
                )

            if not 0 <= value <= 255:
                raise ValueError(
                    f"PID {name.upper()} must be between 0 and 255"
                )

        commands = {
            "p": "SPP",
            "i": "SPI",
            "d": "SPD",
        }

        for name, value in pid.items():
            command = commands[name]

            await self._send(
                f"0{command}{self.slot},{selector},{value}"
            )
    
    async def initialize(self):
        self.state = DriverState.INITIALIZING

        try: 
            print(">> opening HID connection")

            await asyncio.wait_for(
                self.box.setup(),
                timeout=3.0,
            )

            print("<< HID connection opened")

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
                "mode": mode.value,
                "errors": errors,
            }

        except Exception as exc:
            self.state = DriverState.ERROR
            self.last_error = str(exc)
            raise

    async def get_actual_temperature(self) -> float:
        self._ensure_connected()

        raw = await self._send(f"{self.slot}RAT")
        return int(raw) / 10

    async def get_status(self):
        self._ensure_connected()

        actual_temperature = (
            int(await self._send(f"{self.slot}RAT")) / 10
        )

        mode = await self._read_mode()

        errors = await self._send(
            f"{self.slot}REC"
        )

        if not self.state == DriverState.ABORTED:
            if mode == CPACMode.OFF:
                self.state = DriverState.READY
            else:
                self.state = DriverState.RUNNING

        return {
            "state": self.state,
            "slot": self.slot,
            "actual_temperature_c": actual_temperature,
            "mode": mode.value,
            "errors": errors,
        }
    
    async def get_parameters(self):
        self._ensure_connected()

        target_temperature = (
            int(await self._send(f"{self.slot}RTT")) / 10
        )

        return {
            "target_temperature_c": target_temperature,
        }
    
    async def get_configuration(self):
        self._ensure_connected()

        # Basic temperature parameters.
        target_temperature = (
            int(await self._send(f"{self.slot}RTT")) / 10
        )

        min_temperature = (
            int(await self._send(f"{self.slot}RLT")) / 10
        )

        max_temperature = (
            int(await self._send(f"{self.slot}RMT1")) / 10
        )

        # Temperature compensation / tuning.
        heat_cool_offset = (
            int(await self._send(f"{self.slot}RHO")) / 10
        )

        constant_offset = (
            int(await self._send(f"{self.slot}RCO")) / 100
        )

        room_temperature = (
            int(await self._send(f"{self.slot}RRT")) / 10
        )

        boost_offset = (
            int(await self._send(f"{self.slot}RBO")) / 10
        )

        boost_time = int(
            await self._send(f"{self.slot}RBT")
        )

        # PID coefficients.
        pid_heating = {
            "p": int(await self._send(f"{self.slot}RPP0")),
            "i": int(await self._send(f"{self.slot}RPI0")),
            "d": int(await self._send(f"{self.slot}RPD0")),
        }

        pid_cooling = {
            "p": int(await self._send(f"{self.slot}RPP1")),
            "i": int(await self._send(f"{self.slot}RPI1")),
            "d": int(await self._send(f"{self.slot}RPD1")),
        }

        parameter_origin_raw = int(
            await self._send(f"{self.slot}RPO")
        )

        parameter_origin_map = {
            0: "internal_slot_eeprom",
            1: "external_device_eeprom",
            255: "not_set",
        }

        parameter_origin = parameter_origin_map.get(
            parameter_origin_raw,
            f"unknown_{parameter_origin_raw}",
        )

        return {
            "slot": self.slot,

            "temperature": {
                "target_c": target_temperature,
                "min_allowed_c": min_temperature,
                "max_allowed_c": max_temperature,
            },

            "offsets": {
                "heat_cool_offset_c": heat_cool_offset,
                "constant_offset_c": constant_offset,
                "room_temperature_c": room_temperature,
            },

            "boost": {
                "offset_c": boost_offset,
                "time_s": boost_time,
            },

            "pid": {
                "heating": pid_heating,
                "cooling": pid_cooling,
            },

            "parameter_origin": parameter_origin,
        }

    async def set_parameters(self, target_temperature_c: float):
        self._ensure_ready()

        if self.min_temperature is None or self.max_temperature is None:
            raise RuntimeError("Temperature limits are not available")

        if not self.min_temperature <= target_temperature_c <= self.max_temperature:
            raise ValueError(
                f"Target temperature must be between "
                f"{self.min_temperature} and {self.max_temperature} °C"
            )

        target_temperature_c = round(target_temperature_c, 1)
        target_raw = int(round(target_temperature_c * 10))

        await self._send(
            f"{self.slot}STT{target_raw}"
        )

        reported_target = (
            int(await self._send(f"{self.slot}RTT")) / 10
        )

        return {
            "target_temperature_c": reported_target,
        }

    async def set_configuration(
        self,
        *,
        compensation_room_temperature_c: float | None = None,
        boost_offset_c: float | None = None,
        boost_time_s: int | None = None,
        heating_pid: dict | None = None,
        cooling_pid: dict | None = None,
    ):
        self._ensure_ready()

        # Do not change tuning while temperature regulation is active.
        if self.state != DriverState.READY:
            raise RuntimeError(
                "Configuration can only be changed while the CPAC is stopped"
            )

        # Room temperature used for compensation.
        if compensation_room_temperature_c is not None:
            if not 0 <= compensation_room_temperature_c <= 51.0:
                raise ValueError(
                    "Compensation room temperature must be "
                    "between 0 and 51 °C"
                )

            raw = int(round(
                compensation_room_temperature_c * 10
            ))

            # Write to external device EEPROM through mainboard.
            await self._send(
                f"0SRT{self.slot},{raw}"
            )

        # Boost offset.
        if boost_offset_c is not None:
            if not 0 <= boost_offset_c <= 30.0:
                raise ValueError(
                    "Boost offset must be between 0 and 30 °C"
                )

            raw = int(round(boost_offset_c * 10))

            await self._send(
                f"{self.slot}SBO{raw}"
            )

        # Boost time.
        if boost_time_s is not None:
            if not isinstance(boost_time_s, int):
                raise ValueError(
                    "Boost time must be an integer"
                )

            if not 0 <= boost_time_s <= 30000:
                raise ValueError(
                    "Boost time must be between 0 and 30000 seconds"
                )

            await self._send(
                f"{self.slot}SBT{boost_time_s}"
            )

        pid_changed = False

        # Heating PID: selector 0.
        if heating_pid is not None:
            await self._set_pid(
                selector=0,
                pid=heating_pid,
            )
            pid_changed = True

        # Cooling PID: selector 1.
        if cooling_pid is not None:
            await self._set_pid(
                selector=1,
                pid=cooling_pid,
            )
            pid_changed = True

        # External EEPROM PID changes can take several seconds
        # before the slot reports the new values.
        if pid_changed:
            await asyncio.sleep(4.0)

        # Read back actual configuration from hardware.
        return await self.get_configuration()

    async def start(self):
        self._ensure_ready()

        await self._send(f"{self.slot}ATE1")

        mode = await self._read_mode()

        if mode == CPACMode.OFF:
            raise RuntimeError("CPAC did not start temperature regulation")

        self.state = DriverState.RUNNING

        return {
            "state": self.state,
            "slot": self.slot,
            "mode": mode.value,
        }

    async def stop(self):
        self._ensure_ready()

        await self._send(f"{self.slot}ATE0")

        mode = await self._read_mode()

        if mode != CPACMode.OFF:
            self.state = DriverState.ERROR
            raise RuntimeError("CPAC did not stop successfully")
    
        self.state = DriverState.READY

        return {
            "state": self.state,
            "slot": self.slot,
            "mode": CPACMode.OFF.value,
        }

    async def reset(self):
        self._ensure_connected()
        self.state = DriverState.INITIALIZING

        try:
            print(">> sending watchdog reset")

            try:
                await self._send("0SRS0")

            except RuntimeError as exc:
                # On this hardware the controller resets before returning
                # a normal response, so the command times out.
                if "Timeout waiting for response to 0SRS0" not in str(exc):
                    raise

                print("<< reset command caused controller restart")

            # The old HID handle becomes invalid after the reset.
            try:
                await self.box.stop()
            except Exception:
                pass

            # Give the MTC some time to begin booting.
            print("Leaving time for booting")
            await asyncio.sleep(20.0)

            deadline = asyncio.get_running_loop().time() + 25.0

            print(">> waiting for HID device to return")

            while asyncio.get_running_loop().time() < deadline:
                try:
                    # Create a completely fresh HID connection.
                    self.box = InhecoTECControlBox()
                    await asyncio.wait_for(
                        self.box.setup(),
                        timeout=3.0,
                    )

                    print("<< HID connection reopened")
                    break

                except Exception:
                    # Device may still be booting / re-enumerating.
                    try:
                        await self.box.stop()
                    except Exception:
                        pass

                    await asyncio.sleep(0.5)

            else:
                raise RuntimeError(
                    "Controller did not reconnect after reset"
                )

            # First command after reset is expected to report
            # immediate error 6 = Reset detected.
            try:
                self.controller_firmware = await self._send("0RFV1")

            except RuntimeError as exc:
                if "0rfv6" not in str(exc).lower():
                    raise

                print("<< controller reported expected reset-detected code 6")

                await asyncio.sleep(0.2)

                # Retry once after consuming the reset notification.
                self.controller_firmware = await self._send("0RFV1")

            # Verify that the CPAC is still present.
            self.device_type = int(
                await self._send(f"0RTD{self.slot}")
            )

            if self.device_type not in (1, 4):
                raise RuntimeError(
                    f"Slot {self.slot} is not a CPAC after reset "
                    f"(device type={self.device_type})"
                )

            # Refresh cached temperature limits after reboot.
            self.min_temperature = (
                int(await self._send(f"{self.slot}RLT")) / 10
            )

            self.max_temperature = (
                int(await self._send(f"{self.slot}RMT1")) / 10
            )

            # Read actual state after reboot.
            mode = await self._read_mode()

            self.state = (
                DriverState.READY
                if mode == CPACMode.OFF
                else DriverState.RUNNING
            )

            self.last_error = None

            return {
                "state": self.state,
                "slot": self.slot,
                "controller_firmware": self.controller_firmware,
                "device_type": self.device_type,
                "mode": mode.value,
            }

        except Exception as exc:
            self.state = DriverState.ERROR
            self.last_error = str(exc)
            raise

    async def abort(self):
        self._ensure_ready()

        await self._send("0AEO")

        self.state = DriverState.ABORTED

        return {
            "state": self.state,
            "slot": self.slot,
            "scope": "controller",
        }