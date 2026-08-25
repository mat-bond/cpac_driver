import faulthandler

faulthandler.enable()
faulthandler.dump_traceback_later(5, repeat=True)

print("1. Python started", flush=True)

import asyncio

print("2. asyncio imported", flush=True)

from driver import CPACDriver

print("3. driver imported", flush=True)


async def main():
    print("4. creating driver", flush=True)

    driver = CPACDriver(slot=1)

    print("5. driver created", flush=True)

    try:
        print("6. calling initialize", flush=True)

        result = await driver.initialize()

        print("7. initialized", flush=True)
        print(result)

    finally:
        print("8. closing connection", flush=True)
        await driver.box.stop()


if __name__ == "__main__":
    asyncio.run(main())