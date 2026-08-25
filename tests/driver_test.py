import asyncio

from driver import CPACDriver


async def main():
    driver = CPACDriver(slot=1)

    try:
        result = await driver.initialize()

        print("\nInitialization successful:")
        for key, value in result.items():
            print(f"  {key}: {value}")

    finally:
        await driver.box.stop()
        print("\nConnection closed.")


if __name__ == "__main__":
    asyncio.run(main())