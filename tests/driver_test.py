import asyncio

from driver import CPACDriver


async def test_initialize():
    driver = CPACDriver(slot=1)

    try:
        result = await driver.initialize()

        print("\nInitialize result:")
        for key, value in result.items():
            print(f"  {key}: {value}")

    finally:
        await driver.box.stop()


async def test_get_temperature():
    driver = CPACDriver(slot=1)

    try:
        await driver.initialize()

        temperature = await driver.get_actual_temperature()

        print(f"\nActual temperature: {temperature:.1f} °C")

    finally:
        await driver.box.stop()


async def test_get_status():
    driver = CPACDriver(slot=1)

    try:
        await driver.initialize()

        status = await driver.get_status()

        print("\nStatus result:")
        for key, value in status.items():
            print(f"  {key}: {value}")

    finally:
        await driver.box.stop()

async def test_get_parameters():
    driver = CPACDriver(slot=1)

    try:
        await driver.initialize()

        parameters = await driver.get_parameters()
        print("\nParameters: ")

        for key, value in parameters.items():
            print(f"  {key}: {value}")

    finally:
        await driver.box.stop()

async def test_get_configuration():
    driver = CPACDriver(slot=1)

    try:
        await driver.initialize()

        parameters = await driver.get_configuration()
        print("\nConfiguration: ")

        for key, value in parameters.items():
            print(f"  {key}: {value}")

    finally:
        await driver.box.stop()

async def test_set_parameters():
    driver = CPACDriver(slot=1)

    try:
        await driver.initialize()

        result = await driver.set_parameters(20.0)

        print("\nSet parameters result:")
        for key, value in result.items():
            print(f"  {key}: {value}")

        status = await driver.get_status()

        print("\nStatus after setting target:")
        for key, value in status.items():
            print(f"  {key}: {value}")

    finally:
        await driver.box.stop()

async def test_start():
    driver = CPACDriver(slot=1)

    try:
        await driver.initialize()

        # Configure target only.
        await driver.set_parameters(20.0)

        # Start regulation.
        result = await driver.start()

        print("\nRunning for 10 seconds...")
        await asyncio.sleep(10) # To allow visual check on touch screen.

        print("\nStart result:")
        for key, value in result.items():
            print(f"  {key}: {value}")

        status = await driver.get_status()

        print("\nStatus:")
        for key, value in status.items():
            print(f"  {key}: {value}")

    finally:
        # Important: stop regulation before disconnecting.
        try:
            await driver.stop()
        except Exception:
            pass

        await driver.box.stop()

async def test_abort():
    driver = CPACDriver(slot=1)

    try:
        await driver.initialize()
        await driver.set_parameters(20.0)
        await driver.start()

        print("Running...")
        await asyncio.sleep(5)

        print("\nCalling abort...")
        result = await driver.abort()

        print(result)

        # Observe the device here.
        await asyncio.sleep(5)

    finally:
        # Only close the HID connection.
        await driver.box.stop()

async def test_reset():
    driver = CPACDriver(slot=1)

    try:
        await driver.initialize()

        print("\nBefore reset:")
        print(f"  state: {driver.state}")

        result = await driver.reset()

        print("\nReset result:")
        for key, value in result.items():
            print(f"  {key}: {value}")

        status = await driver.get_status()

        print("\nStatus after reset:")
        for key, value in status.items():
            print(f"  {key}: {value}")

    finally:
        await driver.box.stop()

async def test_stop():
    driver = CPACDriver(slot=1)

    try:
        await driver.initialize()
        await driver.set_parameters(20.0)

        await driver.start()

        print("\nRunning for 10 seconds...")
        await asyncio.sleep(10)

        result = await driver.stop()

        print("\nStop result:")
        for key, value in result.items():
            print(f"  {key}: {value}")

        status = await driver.get_status()

        print("\nStatus after stop:")
        for key, value in status.items():
            print(f"  {key}: {value}")

    finally:
        await driver.box.stop()

async def main():
    #await test_initialize()
    #await test_get_temperature()
    #await test_get_status()
    #await test_get_parameters()
    #await test_get_configuration()
    #await test_set_parameters()
    #await test_start()
    #await test_stop()
    #await test_abort()
    #await test_reset()
    pass

if __name__ == "__main__":
    asyncio.run(main())