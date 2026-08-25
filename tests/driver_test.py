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


async def main():
    await test_initialize()
    await test_get_temperature()
    await test_get_status()


if __name__ == "__main__":
    asyncio.run(main())