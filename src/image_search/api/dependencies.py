from fastapi import Request


def get_readiness(request: Request):
    return request.app.state.readiness
