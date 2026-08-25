import asyncio

from pylabrobot.inheco.control_box import InhecoTECControlBox # type: ignore


CONTROLLER_TYPES = {
    0: "STC",
    1: "MTC",
    255: "Unset / behaves as MTC",
}

DEVICE_TYPES = {
    0: "Thermoshake",
    1: "CPAC",
    2: "Teleshake",
    3: "CPLC",
    4: "CPAC 2-TEC",
    5: "HeatPAC",
    6: "Heated Lid",
    12: "Thermoshake AC",
    13: "Teleshake AC",
    14: "Teleshake 95 AC",
    15: "CPLC2",
}

async def send(box, command):
    response = await box.send_command(command)
    await asyncio.sleep(0.1)
    return response

async def main():
    box = InhecoTECControlBox()

    print("Connecting to INHECO controller...")
    await box.setup()
    print("USB connection established.")

    try:

        # Controller/mainboard application firmware
        try:
            firmware = await send(box, "0RFV1")

        except RuntimeError as exc:
            # First command after power-on may report reset code 6.
            print(f"First command returned: {exc}")
            print("Retrying once...")
            await asyncio.sleep(0.2)
            firmware = await send(box, "0RFV1") 

        print(f"MTC/STC firmware: {firmware}")

        # Controller type
        controller_type_raw = await send(box, "0RTD0") # RTD: Report Type (external) Device
        controller_type = CONTROLLER_TYPES.get(
        int(controller_type_raw),
        f"Unknown ({controller_type_raw})"
        )
        print(f"Controller type: {controller_type}")


        # Devices connected
        print("\nScanning slots:")

        for slot in range(1,7):
            try:
                # Article number is useful because 7000255 means no device.
                article = await send(box, f"0RAN{slot}") # RAN: Report Article Number

                if article == "7000255": 
                    print(f"Slot {slot}: empty") 
                    continue
                
                device_type_raw = await send(box, f"0RTD{slot}") 
                device_type = int(device_type_raw)

                name = DEVICE_TYPES.get(device_type, 
                                        f"Unknown device type {device_type}")

                print(f"Slot {slot}: {name}, article={article}")

            except Exception as exc: 
                if "0ran3" in str(exc):
                    print(f"Slot {slot}: unavailable / likely empty")
                else:
                    print(f"Slot {slot}: query failed: {exc}")

    finally:
        await box.stop()
        print("Connection closed.")
        
if __name__ == "__main__":
    asyncio.run(main())
    