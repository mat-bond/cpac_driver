# INHECO CPAC FastAPI Driver

A Python device driver and FastAPI service for controlling an **INHECO Cold Plate Air Cooled Heater/Cooler (CPAC)** through an **INHECO MTC/STC controller**.

The project provides a small hardware abstraction around PyLabRobot's `InhecoTECControlBox`, adds driver state management and validation, and exposes the supported operations through an HTTP API suitable for use by a scheduler or other automation software.

## Features

- USB HID communication with the INHECO MTC/STC controller through PyLabRobot
- CPAC detection and startup validation
- Explicit driver state management
- Read actual plate temperature
- Read and set target temperature
- Start and stop temperature regulation
- Read hardware status and stored error information
- Read controller/device configuration
- Controller-scoped abort behavior
- Watchdog reset with HID reconnect handling
- FastAPI HTTP interface
- Request serialization to prevent concurrent hardware command sequences from interleaving
- Health reporting and HTTP error translation
- Hardware-focused test scripts

## Project Structure

```text
cpac_driver/
├── app.py
├── driver.py
├── tests/
│   ├── communication_test.py
│   └── driver_test.py
├── requirements.txt
└── README.md
```

`driver.py` contains the CPAC hardware abstraction and state machine.

`app.py` owns a single `CPACDriver` instance and exposes it through FastAPI.

`tests/driver_test.py` contains manual hardware-integration tests for the public driver operations.

`tests/communication_test.py` can be used for lower-level MTC/STC communication and device discovery while troubleshooting a controller.

---

## Hardware and Communication Model

The CPAC is not accessed as a serial device. Communication goes through the MTC/STC controller over **USB HID**.

The software stack is:

```text
HTTP client / scheduler
        │
        ▼
FastAPI application
        │
        ▼
CPACService
        │
        ▼
CPACDriver
        │
        ▼
PyLabRobot InhecoTECControlBox
        │
        ▼
USB HID
        │
        ▼
INHECO MTC/STC
        │
        ▼
CPAC
```

The MTC can contain multiple slot modules. This driver instance controls one configured slot at a time.

Valid slot numbers are `1` through `6`.

During initialization, the driver:

1. Opens the HID connection.
2. Reads controller firmware.
3. Verifies the controller type.
4. Reads the article number for the configured slot.
5. Reads the external device type.
6. Accepts CPAC device types `1` and `4`.
7. Reads slot firmware.
8. Reads the hardware temperature limits.
9. Reads the actual temperature.
10. Reads the current heating/cooling state.
11. Reads persistent slot error codes.
12. Sets its initial software state without changing the existing hardware state.

The driver intentionally does **not** stop or reconfigure the CPAC during initialization.

---

## Driver States

The driver tracks its own state separately from the raw hardware commands.

| State | Meaning |
|---|---|
| `disconnected` | HID communication has not been initialized |
| `initializing` | Connection or reset/reconnect is in progress |
| `ready` | Connected and temperature regulation is stopped |
| `running` | Connected and temperature regulation is active |
| `error` | A driver operation failed and the driver requires recovery/reinitialization |
| `aborted` | An abort was issued; normal control commands are blocked until reset/recovery |

Read operations such as status and temperature require the driver to be connected.

Control operations such as setting parameters, starting, stopping, and aborting require the driver to be ready for commands.

After an abort, normal control commands are intentionally rejected.

---

## Supported Operations

### Initialize

Initializes the HID transport, validates that the configured slot contains a CPAC, reads firmware/device metadata, hardware temperature limits, temperature, state, and stored errors.

Driver method:

```python
await driver.initialize()
```

API:

```http
POST /initialize
```

Initialization through the FastAPI service is idempotent. If the driver is already initialized, the API returns the current state rather than opening another HID connection.

If a previous initialization attempt left the driver in the `error` state, the service closes the old transport, creates a new `CPACDriver`, and retries initialization.

---

### Read Actual Temperature

Reads the current compensated CPAC surface temperature.

Driver method:

```python
temperature = await driver.get_actual_temperature()
```

API:

```http
GET /temperature
```

Example response:

```json
{
  "actual_temperature_c": 27.4
}
```

---

### Get Status

Reads:

- driver state
- configured slot
- actual temperature
- heating/cooling/off mode
- stored slot error codes

Driver method:

```python
status = await driver.get_status()
```

API:

```http
GET /status
```

Example:

```json
{
  "state": "ready",
  "slot": 1,
  "actual_temperature_c": 27.4,
  "mode": "off",
  "errors": "_06"
}
```

The `errors` value is the MTC/STC persistent error-memory response. Stored errors may describe previous hardware events and are not necessarily caused by the latest API request.

---

## Parameters

Runtime parameters are intentionally kept separate from hardware configuration.

At present, the modifiable runtime parameter is:

```text
target_temperature_c
```

### Get Parameters

Driver method:

```python
parameters = await driver.get_parameters()
```

API:

```http
GET /parameters
```

Example:

```json
{
  "target_temperature_c": 20.0
}
```

### Set Parameters

Setting the target temperature does **not** start heating or cooling.

Driver method:

```python
await driver.set_parameters(20.0)
```

API:

```http
PUT /parameters
Content-Type: application/json
```

Body:

```json
{
  "target_temperature_c": 20.0
}
```

The requested target is validated against the minimum and maximum temperature values read from the device during initialization.

The temperature is rounded to one decimal place before being sent to the controller.

After writing the target, the driver reads the target back from the device and returns the reported value.

---

## Configuration

Configuration is exposed as **read-only**.

API:

```http
GET /configuration
```

Driver method:

```python
configuration = await driver.get_configuration()
```

The response includes:

```json
{
  "temperature_limits": {
    "min_allowed_c": -9.9,
    "max_allowed_c": 120.0
  },
  "offsets": {
    "heat_cool_offset_c": 0.9,
    "constant_offset_c": -0.26,
    "compensation_room_temperature_c": 23.0
  },
  "boost": {
    "offset_c": 0.0,
    "time_s": 0
  },
  "pid": {
    "heating": {
      "p": 100,
      "i": 50,
      "d": 0
    },
    "cooling": {
      "p": 100,
      "i": 100,
      "d": 0
    }
  },
  "parameter_origin": "external_device_eeprom"
}
```

There is intentionally no `PUT /configuration` endpoint.

External EEPROM configuration writes did not behave reliably enough on the installed controller/firmware during hardware validation. Some configuration values are also factory-level settings. Rather than expose an API that could appear successful while leaving the hardware in an uncertain state, configuration is kept read-only.

---

## Start Temperature Regulation

`start()` enables temperature regulation using the target temperature previously written with `set_parameters()`.

Typical sequence:

```python
await driver.set_parameters(20.0)
await driver.start()
```

API:

```http
POST /start
```

The driver sends the temperature-enable command and reads the controller mode back. If the controller still reports `off`, the operation fails instead of silently setting the software state to running.

---

## Stop Temperature Regulation

Stops temperature regulation for the configured CPAC slot.

Driver method:

```python
await driver.stop()
```

API:

```http
POST /stop
```

The driver:

1. Sends the slot-specific temperature-disable command.
2. Reads the mode back.
3. Requires the reported mode to be `off`.
4. Transitions the driver to `ready`.

If the mode does not become `off`, the driver enters the `error` state and raises an exception.

---

## Abort

Abort is intentionally stronger than a normal stop.

Current behavior:

1. Perform the normal slot-specific `stop()` sequence.
2. Send the controller-level emergency-off command.
3. Transition the software state to `aborted`.

Driver method:

```python
await driver.abort()
```

API:

```http
POST /abort
```

Example response:

```json
{
  "state": "aborted",
  "slot": 1,
  "scope": "controller"
}
```

The abort operation is treated as **controller-scoped**. On a controller with multiple connected devices, the emergency-off portion must therefore be considered capable of affecting more than the configured CPAC slot.

After abort, the driver remains in `aborted` state and blocks normal control operations until recovery/reset.

---

## Reset

The reset implementation uses the MTC/STC watchdog-reset path and must account for USB HID re-enumeration.

API:

```http
POST /reset
```

The sequence is:

1. Send the watchdog reset command.
2. Accept a timeout from that command if the controller resets before returning its normal response.
3. Close the now-invalid HID handle.
4. Wait for the controller to begin rebooting.
5. Repeatedly attempt to establish a fresh HID connection.
6. Handle the expected first-command `reset detected` response.
7. Verify that the configured slot is still a CPAC.
8. Refresh cached temperature limits.
9. Read the current hardware mode.
10. Return the driver to `ready` or `running`.

Reset is the most firmware-sensitive operation in the driver. It should be validated on the specific controller/firmware combination used in production.

A reset should not be used as a substitute for a normal `stop()`.

---

## FastAPI Service

The FastAPI layer is intentionally thin. Hardware-specific behavior remains in `CPACDriver`.

The service owns **one persistent driver instance** rather than creating a new HID connection for every HTTP request.

This is important because the MTC/STC is a stateful hardware resource and concurrent connections or repeated reconnects are not appropriate request-level behavior.

### API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Report API/driver health and state |
| `POST` | `/initialize` | Connect and initialize the hardware driver |
| `GET` | `/status` | Read CPAC status |
| `GET` | `/temperature` | Read actual temperature |
| `GET` | `/parameters` | Read runtime parameters |
| `PUT` | `/parameters` | Set target temperature |
| `GET` | `/configuration` | Read hardware/control configuration |
| `POST` | `/start` | Start temperature regulation |
| `POST` | `/stop` | Stop temperature regulation |
| `POST` | `/abort` | Stop and issue controller-scoped emergency off |
| `POST` | `/reset` | Perform watchdog reset and reconnect |

No configuration-write endpoint is exposed.

---

## Concurrency and Locking

The project uses two locking levels with different responsibilities.

The lock inside `CPACDriver._send()` protects an individual HID command, ensuring that only one low-level message is sent to the MTC/STC at a time.

The `CPACService` lock protects an entire API operation. A higher-level operation may contain several HID commands that must remain logically grouped. For example, `start()` first enables regulation and then reads the mode back to verify that the operation succeeded. Without the service lock, another HTTP request could issue a stop command between those two commands and produce an inconsistent result.

In short:

```text
CPACDriver._send() lock  -> transport-level serialization
CPACService lock         -> operation-level serialization
```

This prevents concurrent HTTP requests from interleaving multi-step hardware operations.

---

## Health Endpoint

```http
GET /health
```

Example:

```json
{
  "healthy": true,
  "state": "ready",
  "slot": 1,
  "last_error": null
}
```

The current API considers `ready`, `running`, and `aborted` to be connected/healthy driver states.

`aborted` therefore means that the service is alive and the device remains represented by the driver, **not** that new control operations are permitted.

The `last_error` field stores the latest initialization/reset-level driver failure when available.

---
## Installation

Create and activate a project virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Upgrade pip:

```bash
python -m pip install --upgrade pip
```

Install project dependencies.

If `requirements.txt` is present:

```bash
python -m pip install -r requirements.txt
```

At minimum, the application requires:

```text
fastapi
uvicorn
pylabrobot
```

A working HID backend is also required by the PyLabRobot INHECO transport.

For development, using `python -m pip` rather than a bare `pip` command helps ensure dependencies are installed into the active virtual environment.

---

## Configuration

The controlled slot is configured through the `CPAC_SLOT` environment variable.

Default:

```text
CPAC_SLOT=1
```

Example:

```bash
export CPAC_SLOT=2
```

The value must be between `1` and `6`.

---

## Running the API

Activate the virtual environment:

```bash
source .venv/bin/activate
```

Run Uvicorn from the repository root:

```bash
PYTHONPATH=. python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

The API will be available at:

```text
http://127.0.0.1:8000
```

FastAPI Swagger documentation:

```text
http://127.0.0.1:8000/docs
```

The application deliberately does **not** initialize the physical hardware when the web server starts. The client or scheduler must explicitly call:

```http
POST /initialize
```

This keeps web-process startup separate from physical-device actions.

---

## Example API Session

### 1. Initialize

```bash
curl -X POST http://127.0.0.1:8000/initialize
```

### 2. Check health

```bash
curl http://127.0.0.1:8000/health
```

### 3. Read status

```bash
curl http://127.0.0.1:8000/status
```

### 4. Set target temperature

```bash
curl \
  -X PUT \
  http://127.0.0.1:8000/parameters \
  -H "Content-Type: application/json" \
  -d '{"target_temperature_c": 20.0}'
```

### 5. Start regulation

```bash
curl -X POST http://127.0.0.1:8000/start
```

### 6. Check temperature/status

```bash
curl http://127.0.0.1:8000/temperature
curl http://127.0.0.1:8000/status
```

### 7. Stop

```bash
curl -X POST http://127.0.0.1:8000/stop
```

---

## Recommended Demonstration Sequence

For a hardware demonstration, use the following order:

```text
POST /initialize
GET  /health
GET  /status
GET  /temperature
GET  /parameters
GET  /configuration
PUT  /parameters
POST /start
GET  /status
POST /stop
GET  /status
```

Abort should be demonstrated separately because it deliberately leaves the software driver in the `aborted` state.

Reset should generally be demonstrated last because it causes controller reboot and USB HID re-enumeration.

---

## Hardware Testing

The repository includes hardware-facing tests for the public driver methods.

Typical manual test coverage includes:

- initialization
- actual temperature
- status
- get parameters
- get configuration
- set parameters
- start
- stop
- abort
- reset

Run the hardware test file from the repository root:

```bash
PYTHONPATH=. python tests/driver_test.py
```

The tests are intentionally explicit/manual rather than automatically running every physical operation in sequence. Heating/cooling, abort, and reset operations affect real hardware and should only be enabled deliberately.

A typical test function creates one driver, initializes it, performs one operation, and closes the HID connection in `finally`.

Tests that start temperature regulation should stop the CPAC before disconnecting.

Abort tests intentionally avoid automatically issuing another stop command after abort, so cleanup does not hide the state produced by the operation being tested.

---

## Low-Level Command Notes

The driver currently uses the following INHECO command families internally:

```text
RFV  firmware information
RTD  controller/external device type
RAN  article number
RLT  minimum allowed device temperature
RMT  maximum allowed device temperature
RAT  actual temperature
RTT  target temperature
STT  set target temperature
RHE  heating/cooling enable status
ATE  temperature regulation enable/disable
REC  persistent error memory
RHO  heat/cool offset
RCO  constant offset
RRT  room-temperature compensation value
RBO  boost offset
RBT  boost time
RPP  PID proportional coefficient
RPI  PID integral coefficient
RPD  PID differential coefficient
RPO  parameter origin
AEO  emergency off
SRS  system reset
```

Application code should not normally issue these strings directly. They are implementation details of `CPACDriver`.

---

## Timeouts

Each low-level command is sent through `_send()`.

`_send()`:

- serializes access using an asyncio lock
- forwards a device timeout to PyLabRobot
- wraps that with a slightly longer application-level timeout
- converts timeout failures into a clear `RuntimeError`
- inserts a short delay between commands

This keeps timeout behavior centralized and avoids duplicating transport handling throughout the driver.

State-changing operations should not be blindly retried if command execution is uncertain. A timeout can mean that the caller did not receive a valid response, not necessarily that the controller did nothing.

---

## Safety and Production Considerations

This project intentionally favors a smaller set of verified hardware operations over exposing every command in the INHECO firmware command set.

Important behaviors:

- Target temperature is checked against hardware-reported limits before being written.
- Setting a target does not automatically start temperature regulation.
- Start and stop operations verify the resulting controller mode.
- Configuration writes are not exposed.
- Abort performs a normal stop before the controller-scoped emergency-off action.
- Aborted state blocks further normal control.
- Reset includes explicit HID reconnect handling.
- API operations are serialized.
- Hardware initialization is explicit rather than automatic at FastAPI startup.

For deployment on different MTC/STC firmware versions, hardware behavior should be revalidated. The INHECO command documentation covers multiple firmware generations, and older controllers can differ in timing and command behavior.

---

## Known Limitations

### Configuration writes

Configuration is read-only. External EEPROM configuration writes were not sufficiently reliable on the validated controller/firmware combination to expose through the public API.

### Reset behavior

Reset depends on controller reboot timing and USB HID re-enumeration. It is more firmware- and host-dependent than normal read/control operations.

### One service instance per controller

The FastAPI application owns a single `CPACDriver` and a single HID transport. Running multiple worker processes against the same physical controller is not supported by this design.

For Uvicorn, run a single worker for the physical device service.

### Multi-slot controllers

A `CPACDriver` instance represents one configured CPAC slot.

The controller itself may contain multiple slots, and some controller-level commands such as emergency off may affect devices outside the configured slot. Applications must account for this before using controller-scoped operations.

### Persistent error memory

`REC` reports stored error history. A returned error code may predate the current API request. Error occurrence details should be inspected before attributing a stored error to the most recent command.

---

## Development Notes

The intended separation of responsibilities is:

```text
app.py
  HTTP API
  request validation
  operation-level locking
  error-to-HTTP translation
  service lifecycle

driver.py
  hardware state machine
  CPAC semantics
  target validation
  command sequencing
  transport-level locking
  hardware verification

PyLabRobot
  HID transport
  INHECO packet/protocol handling
```

Keeping these layers separate makes it possible to replace the HTTP interface, test the hardware driver directly, or mock the transport without moving hardware-specific behavior into the web application.

---

## Shutdown

FastAPI uses a lifespan handler to close the HID connection when the application shuts down.

The service does not automatically stop active temperature regulation on web-server shutdown. Hardware state and transport lifetime are deliberately separate concerns.

If application policy requires stopping the device before process exit, add that behavior explicitly and validate it for the target workflow rather than assuming that closing USB communication should alter the current CPAC state.
