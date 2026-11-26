"""Helpers that insert the smallest valid row of each table, so a test only spells out what it is about."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from labtrack.db import scalar

BRT = timezone(timedelta(hours=-3))  # Brazil has no daylight saving time since 2019


def at(day: str, hm: str = "09:00") -> datetime:
    """A moment in the lab's local time."""
    return datetime.fromisoformat(f"{day}T{hm}:00").replace(tzinfo=BRT)


@contextmanager
def violates(conn: psycopg.Connection, exc_type: type[Exception], constraint: str | None = None) -> Iterator[None]:
    """Expect the block to fail with `exc_type` (and, if given, that constraint). Uses a savepoint, so the
    surrounding test transaction stays usable afterwards."""
    with pytest.raises(exc_type) as info, conn.transaction():
        yield
    if constraint is not None:
        assert info.value.diag.constraint_name == constraint  # type: ignore[attr-defined]


class Lab:
    """Builds rows with valid defaults. Every method takes overrides and returns the new row's id."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self.n = 0

    def _next(self) -> int:
        self.n += 1
        return self.n

    def insert(self, table: str, returning: str, **values: Any) -> int:
        columns = list(values)
        query = sql.SQL("INSERT INTO lab.{} ({}) VALUES ({}) RETURNING {}").format(
            sql.Identifier(table),
            sql.SQL(", ").join(sql.Identifier(c) for c in columns),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            sql.Identifier(returning),
        )
        return int(scalar(self.conn, query, [values[c] for c in columns]))

    # ---- slowly changing tables -------------------------------------------------------------
    def study(self, **kw: Any) -> int:
        n = self._next()
        values = dict(code=f"TST-{n:02d}", title="A test study", started_on="2024-01-01", ended_on=None,
                      planned_visits=4, target_n=10)
        return self.insert("study", "study_id", **{**values, **kw})

    def researcher(self, **kw: Any) -> int:
        n = self._next()
        values = dict(full_name=f"Test Researcher {n}", role="msc", email=f"r{n}@lab.example",
                      hired_on="2020-01-01", left_on=None)
        return self.insert("researcher", "researcher_id", **{**values, **kw})

    def participant(self, **kw: Any) -> int:
        n = self._next()
        values = dict(code=f"P{n:04d}", birth_year=1990, sex="F", dominant_hand="right",
                      consent_signed_on="2024-01-02", withdrawn_on=None)
        return self.insert("participant", "participant_id", **{**values, **kw})

    def enrollment(self, study_id: int, participant_id: int, **kw: Any) -> None:
        values = dict(study_id=study_id, participant_id=participant_id, group_label="control",
                      enrolled_on="2024-01-10")
        self.insert("enrollment", "study_id", **{**values, **kw})

    def device(self, **kw: Any) -> int:
        n = self._next()
        values = dict(kind="emg_amplifier", model="Test Amp", serial_no=f"SN-T-{n:03d}", home_room="R01",
                      acquired_on="2020-01-01", retired_on=None)
        return self.insert("device", "device_id", **{**values, **kw})

    def calibration(self, device_id: int, researcher_id: int, **kw: Any) -> int:
        values = dict(device_id=device_id, performed_on="2024-01-05", performed_by=researcher_id, passed=True,
                      valid_until="2024-05-04", notes=None)
        return self.insert("calibration", "calibration_id", **{**values, **kw})

    # ---- the tables that grow ---------------------------------------------------------------
    def session(self, study_id: int, participant_id: int, researcher_id: int, **kw: Any) -> int:
        values = dict(study_id=study_id, participant_id=participant_id, researcher_id=researcher_id,
                      visit_no=1, room="R01", starts_at=at("2024-02-05"), ends_at=at("2024-02-05", "10:30"),
                      status="scheduled", notes=Jsonb({}), protocol_version="v2")
        return self.insert("session", "session_id", **{**values, **kw})

    def session_device(self, session_id: int, device_id: int) -> None:
        self.insert("session_device", "session_id", session_id=session_id, device_id=device_id)

    def recording(self, session_id: int, device_id: int, **kw: Any) -> int:
        n = self._next()
        values = dict(session_id=session_id, device_id=device_id, modality="emg", block_no=1,
                      sampling_rate_hz=2000, n_channels=4, recorded_at=at("2024-02-05", "09:05"),
                      duration_s=60, size_bytes=1000, sha256=f"{n:064x}", storage_uri=f"s3://bucket/{n}.edf")
        return self.insert("recording", "recording_id", **{**values, **kw})

    def trial(self, recording_id: int, **kw: Any) -> int:
        values = dict(recording_id=recording_id, trial_no=1, condition="hold_20_fb", onset_s=2, duration_s=6,
                      valid=True, reject_reason=None)
        return self.insert("trial", "trial_id", **{**values, **kw})

    # ---- a ready-made world -----------------------------------------------------------------
    def world(self) -> World:
        """A study, a researcher, an enrolled participant and a device: enough to book a session."""
        study = self.study()
        researcher = self.researcher()
        participant = self.participant()
        self.enrollment(study, participant)
        device = self.device()
        return World(study, researcher, participant, device)

    def booked_session(self, w: World, **kw: Any) -> int:
        """A session of the world, with the world's device booked for it."""
        session = self.session(w.study, w.participant, w.researcher, **kw)
        self.session_device(session, w.device)
        return session


class World:
    def __init__(self, study: int, researcher: int, participant: int, device: int) -> None:
        self.study, self.researcher, self.participant, self.device = study, researcher, participant, device


class Scene:
    """What healthy_scene() built: the ids a test needs to damage something on purpose."""

    def __init__(self, lab: Lab, world: World, session: int, recording: int, trial: int) -> None:
        self.lab, self.world, self.session, self.recording, self.trial = lab, world, session, recording, trial


def healthy_scene(conn: psycopg.Connection) -> Scene:
    """A completed session with one recording, its four channels, one trial and one valid feature value:
    a lab in which every data-quality check finds nothing."""
    lab = Lab(conn)
    world = lab.world()
    session = lab.booked_session(world, status="completed")
    recording = lab.recording(session, world.device)            # n_channels defaults to 4
    for n in range(1, 5):
        conn.execute("INSERT INTO lab.channel VALUES (%s, %s, %s, 'uV')", (recording, n, f"ch{n}"))
    trial = lab.trial(recording)
    conn.execute("INSERT INTO lab.trial_feature VALUES (%s, 1, 1, 10.0)", (trial,))   # feature 1 is an EMG one
    return Scene(lab, world, session, recording, trial)
