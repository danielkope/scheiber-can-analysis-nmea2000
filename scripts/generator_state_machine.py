"""Context-aware receive-only generator lifecycle reconstruction.

The same 0x005A1020 frequency signal can change when the associated AC path is
switched, so frequency alone is not treated as a global engine-state oracle.
It advances the lifecycle only while a START or STOP transaction is active.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from scheiber_can_core import CandumpFrame, GENERATOR_STATUS_ENUM, u16le

GENERATOR_COMMAND_CAN_ID = 0x02460B88
GENERATOR_STATUS_CAN_ID = 0x02440B88
GENERATOR_FREQUENCY_CAN_ID = 0x005A1020
GENERATOR_RUNNING_FREQUENCY_RAW = 500  # 50.0 Hz at scale 0.1 Hz/count
GENERATOR_STOPPED_FREQUENCY_RAW = 0


@dataclass(frozen=True)
class GeneratorLifecycleEvent:
    line_number: int
    timestamp: float
    relative_seconds: float
    interface: str
    can_id: str
    data_hex: str
    signal: str
    raw_value: Any
    engineering_value: Any
    state_before: str
    state_after: str
    transition_phase: str
    accepted: bool
    confidence: str
    notes: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GeneratorLifecycleTracker:
    """Incrementally reconstruct generator state without transmitting frames."""

    def __init__(self) -> None:
        self.state = "UNKNOWN"
        self.transition_phase = "none"

    def _event(
        self,
        frame: CandumpFrame,
        start_ts: float,
        *,
        signal: str,
        raw_value: Any,
        engineering_value: Any,
        state_before: str,
        accepted: bool,
        confidence: str,
        notes: str,
    ) -> GeneratorLifecycleEvent:
        return GeneratorLifecycleEvent(
            line_number=frame.line_number,
            timestamp=frame.timestamp,
            relative_seconds=round(frame.timestamp - start_ts, 6),
            interface=frame.interface,
            can_id=frame.can_id_hex,
            data_hex=frame.data_hex,
            signal=signal,
            raw_value=raw_value,
            engineering_value=engineering_value,
            state_before=state_before,
            state_after=self.state,
            transition_phase=self.transition_phase,
            accepted=accepted,
            confidence=confidence,
            notes=notes,
        )

    def process(self, frame: CandumpFrame, start_ts: float) -> list[GeneratorLifecycleEvent]:
        before = self.state

        if frame.can_id == GENERATOR_COMMAND_CAN_ID and len(frame.data) == 1:
            raw = frame.data[0]
            if raw == 0x01:
                self.transition_phase = "start"
                self.state = "STARTING"
                return [self._event(
                    frame,
                    start_ts,
                    signal="EXTERNAL_START_COMMAND",
                    raw_value=raw,
                    engineering_value="START",
                    state_before=before,
                    accepted=True,
                    confidence="high",
                    notes="0x02460B88#01 begins the externally requested START transaction.",
                )]
            if raw == 0x02:
                self.transition_phase = "stop"
                self.state = "STOPPING"
                return [self._event(
                    frame,
                    start_ts,
                    signal="EXTERNAL_STOP_COMMAND",
                    raw_value=raw,
                    engineering_value="STOP",
                    state_before=before,
                    accepted=True,
                    confidence="high",
                    notes="0x02460B88#02 begins the externally requested STOP transaction.",
                )]
            return [self._event(
                frame,
                start_ts,
                signal="UNKNOWN_EXTERNAL_COMMAND",
                raw_value=raw,
                engineering_value=f"UNKNOWN_0x{raw:02X}",
                state_before=before,
                accepted=False,
                confidence="low",
                notes="Unknown command byte; lifecycle state was not changed.",
            )]

        if frame.can_id == GENERATOR_STATUS_CAN_ID and len(frame.data) == 1:
            raw = frame.data[0]
            mapped = GENERATOR_STATUS_ENUM.get(raw)
            if mapped is None:
                return [self._event(
                    frame,
                    start_ts,
                    signal="UNKNOWN_GENERATOR_STATUS",
                    raw_value=raw,
                    engineering_value=f"UNKNOWN_0x{raw:02X}",
                    state_before=before,
                    accepted=False,
                    confidence="low",
                    notes="Unknown 0x02440B88 status byte; lifecycle state was not changed.",
                )]

            if raw in (0x02, 0x03):
                if self.state in {"RUNNING", "RUNNING_SETTLED"}:
                    return [self._event(
                        frame,
                        start_ts,
                        signal="STARTING_STATUS_LINGER",
                        raw_value=raw,
                        engineering_value=mapped,
                        state_before=before,
                        accepted=True,
                        confidence="high",
                        notes="STARTING status observed after the 50 Hz milestone; retained current running state rather than regressing.",
                    )]
                self.transition_phase = "start"
                self.state = "STARTING"
                return [self._event(
                    frame,
                    start_ts,
                    signal="STARTING_STATUS_CONFIRMED",
                    raw_value=raw,
                    engineering_value=mapped,
                    state_before=before,
                    accepted=True,
                    confidence="high",
                    notes="0x02440B88 values 0x02 and 0x03 confirm STARTING.",
                )]

            if raw in (0x04, 0x05):
                if self.state in {"STOPPED", "OFF_IDLE"}:
                    return [self._event(
                        frame,
                        start_ts,
                        signal="STOPPING_STATUS_LINGER",
                        raw_value=raw,
                        engineering_value=mapped,
                        state_before=before,
                        accepted=True,
                        confidence="high",
                        notes="STOPPING status observed after the zero-frequency milestone; retained the later state.",
                    )]
                self.transition_phase = "stop"
                self.state = "STOPPING"
                return [self._event(
                    frame,
                    start_ts,
                    signal="STOPPING_STATUS_CONFIRMED",
                    raw_value=raw,
                    engineering_value=mapped,
                    state_before=before,
                    accepted=True,
                    confidence="high",
                    notes="0x02440B88 values 0x05 and 0x04 confirm STOPPING.",
                )]

            if raw == 0x01:
                self.state = "RUNNING_SETTLED"
                self.transition_phase = "none"
                return [self._event(
                    frame,
                    start_ts,
                    signal="RUNNING_SETTLED_STATUS",
                    raw_value=raw,
                    engineering_value=mapped,
                    state_before=before,
                    accepted=True,
                    confidence="high",
                    notes="0x02440B88#01 is the settled terminal state after startup.",
                )]

            self.state = "OFF_IDLE"
            self.transition_phase = "none"
            return [self._event(
                frame,
                start_ts,
                signal="OFF_IDLE_STATUS",
                raw_value=raw,
                engineering_value=mapped,
                state_before=before,
                accepted=True,
                confidence="high",
                notes="0x02440B88#00 is the final OFF/IDLE terminal state. It was confirmed in follow-on work but is absent from the baseline capture.",
            )]

        if frame.can_id == GENERATOR_FREQUENCY_CAN_ID and len(frame.data) == 8:
            raw = u16le(frame.data, 0)
            hz = round(raw / 10.0, 1)

            if raw == GENERATOR_RUNNING_FREQUENCY_RAW:
                if self.transition_phase == "start" or self.state == "STARTING":
                    self.state = "RUNNING"
                    return [self._event(
                        frame,
                        start_ts,
                        signal="RUNNING_FREQUENCY_MILESTONE",
                        raw_value=raw,
                        engineering_value=hz,
                        state_before=before,
                        accepted=True,
                        confidence="high",
                        notes="0x005A1020 reached 50.0 Hz during an active START transaction.",
                    )]
                return [self._event(
                    frame,
                    start_ts,
                    signal="AC_PRESENT_OUTSIDE_START_TRANSACTION",
                    raw_value=raw,
                    engineering_value=hz,
                    state_before=before,
                    accepted=False,
                    confidence="high for frequency; context required for lifecycle",
                    notes="50.0 Hz was observed without an active START transaction; source switching can change this signal, so lifecycle state was not changed.",
                )]

            if raw == GENERATOR_STOPPED_FREQUENCY_RAW:
                if self.transition_phase == "stop" or self.state == "STOPPING":
                    self.state = "STOPPED"
                    return [self._event(
                        frame,
                        start_ts,
                        signal="STOPPED_FREQUENCY_MILESTONE",
                        raw_value=raw,
                        engineering_value=hz,
                        state_before=before,
                        accepted=True,
                        confidence="high",
                        notes="0x005A1020 reached 0.0 Hz during an active STOP transaction.",
                    )]
                return [self._event(
                    frame,
                    start_ts,
                    signal="AC_ABSENT_OUTSIDE_STOP_TRANSACTION",
                    raw_value=raw,
                    engineering_value=hz,
                    state_before=before,
                    accepted=False,
                    confidence="high for frequency; context required for lifecycle",
                    notes="0.0 Hz was observed without an active STOP transaction; this also occurs when the associated AC path is disconnected.",
                )]

            if self.transition_phase == "start":
                return [self._event(
                    frame,
                    start_ts,
                    signal="START_FREQUENCY_BUILD",
                    raw_value=raw,
                    engineering_value=hz,
                    state_before=before,
                    accepted=True,
                    confidence="high for frequency",
                    notes="Non-terminal frequency observed while the START transaction remains active.",
                )]
            if self.transition_phase == "stop":
                return [self._event(
                    frame,
                    start_ts,
                    signal="STOP_FREQUENCY_DECAY",
                    raw_value=raw,
                    engineering_value=hz,
                    state_before=before,
                    accepted=True,
                    confidence="high for frequency",
                    notes="Non-zero transitional frequency observed while the STOP transaction remains active.",
                )]
            return [self._event(
                frame,
                start_ts,
                signal="TRANSITIONAL_FREQUENCY_OUTSIDE_TRANSACTION",
                raw_value=raw,
                engineering_value=hz,
                state_before=before,
                accepted=False,
                confidence="high for frequency; context required for lifecycle",
                notes="Frequency decoded, but no active generator command transaction exists.",
            )]

        return []


def track_generator_lifecycle(
    frames: Iterable[CandumpFrame], start_ts: float
) -> list[GeneratorLifecycleEvent]:
    tracker = GeneratorLifecycleTracker()
    events: list[GeneratorLifecycleEvent] = []
    for frame in frames:
        events.extend(tracker.process(frame, start_ts))
    return events
