import os
import signal
from .config import BridgeConfig
from .service import Service
from .app import create_app


def main():
    config = BridgeConfig.load(os.getenv("BRIDGE_CONFIG", "/config/bridge-config.json"))
    if not os.getenv(config.data["login_token_env"]):
        raise SystemExit("Set the bridge login token before starting")
    service = Service(config)

    def shutdown(*_):
        service.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    service.start()
    try:
        create_app(service).run(
            host="0.0.0.0",
            port=int(os.getenv("BRIDGE_PORT", "8008")),
            threaded=True,
            use_reloader=False,
        )
    finally:
        service.close()


if __name__ == "__main__":
    main()
