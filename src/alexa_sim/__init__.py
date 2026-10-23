"""Alexa+ simulator: an Echo Show–style client that plays Alexa+ for the demo (spec §5.9).

``uv run alexa-sim`` serves it at ``http://127.0.0.1:8100``.
"""


def main() -> None:
    import logging

    import uvicorn

    from alexa_sim.app import build_app, make_sim
    from alexa_sim.config import load_sim_settings

    logging.basicConfig(level=logging.INFO)
    settings = load_sim_settings()
    uvicorn.run(build_app(make_sim(settings)), host=settings.host, port=settings.port)
