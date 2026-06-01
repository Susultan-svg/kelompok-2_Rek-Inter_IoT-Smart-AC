from dataclasses import dataclass


@dataclass
class ControlState:
    mode: str
    setpoint: float
    ac_on: bool = False


def decide_automatic_control(
    state: ControlState,
    temperature: float | None,
    motion: bool,
) -> tuple[str | None, str]:
    if state.mode != "auto":
        return None, "manual mode"

    if not motion:
        return "OFF", "no motion detected"

    if temperature is None:
        return "ON", "motion detected and temperature unavailable"

    if temperature > state.setpoint:
        return "ON", "temperature above setpoint"

    if temperature <= state.setpoint - 1:
        return "OFF", "temperature below hysteresis"

    return None, "inside hysteresis band"
