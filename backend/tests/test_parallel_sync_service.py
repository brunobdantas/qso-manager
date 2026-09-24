import threading
import time

from app.services.parallel_sync_service import ParallelSyncCoordinator


class FakeSyncService:
    SYNC_PROVIDERS = ("QRZ", "WRL", "CLUBLOG", "LOTW")

    def __init__(self, shared):
        self.shared = shared

    def status(self):
        return {
            "providers": [
                {"provider": p, "label": p, "configured": True}
                for p in self.SYNC_PROVIDERS
            ]
        }

    def sync(self, provider):
        with self.shared["lock"]:
            self.shared["active"] += 1
            self.shared["max_active"] = max(self.shared["max_active"], self.shared["active"])
        try:
            time.sleep(0.06)
            if provider == "CLUBLOG" and self.shared.get("fail_clublog"):
                raise RuntimeError("club log unavailable")
            return {"ok": True, "provider": provider, "records": 100 + len(provider)}
        finally:
            with self.shared["lock"]:
                self.shared["active"] -= 1


def make_coordinator(fail_clublog=False):
    shared = {
        "lock": threading.Lock(),
        "active": 0,
        "max_active": 0,
        "fail_clublog": fail_clublog,
    }
    return ParallelSyncCoordinator(
        service_factory=lambda: FakeSyncService(shared),
        max_workers=4,
    ), shared


def wait_done(coordinator, job_id, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = coordinator.get(job_id)
        if job["status"] in {"completed", "completed_with_errors"}:
            return job
        time.sleep(0.01)
    raise AssertionError("sync job did not finish")


def test_parallel_sync_runs_providers_concurrently_and_reports_progress():
    coordinator, shared = make_coordinator()

    started = coordinator.start()
    assert started["status"] in {"queued", "running"}
    assert started["total"] == 4
    assert started["parallelism"] == 4

    done = wait_done(coordinator, started["job_id"])

    assert done["status"] == "completed"
    assert done["progress"] == 100
    assert done["completed"] == 4
    assert done["succeeded"] == 4
    assert done["failed"] == 0
    assert shared["max_active"] >= 2
    assert all(
        row["status"] == "success"
        for row in done["providers"].values()
        if row["configured"]
    )


def test_parallel_sync_isolates_provider_failure_and_finishes_other_downloads():
    coordinator, shared = make_coordinator(fail_clublog=True)

    started = coordinator.start()
    done = wait_done(coordinator, started["job_id"])

    assert done["status"] == "completed_with_errors"
    assert done["progress"] == 100
    assert done["succeeded"] == 3
    assert done["failed"] == 1
    assert done["providers"]["CLUBLOG"]["status"] == "failed"
    assert "unavailable" in done["providers"]["CLUBLOG"]["error"]
    assert done["providers"]["QRZ"]["status"] == "success"
    assert done["providers"]["LOTW"]["status"] == "success"
    assert shared["max_active"] >= 2


def test_start_does_not_launch_duplicate_all_source_job():
    coordinator, _shared = make_coordinator()

    first = coordinator.start()
    second = coordinator.start()

    assert second["job_id"] == first["job_id"]
    done = wait_done(coordinator, first["job_id"])
    assert done["completed"] == 4


class PartiallyConfiguredService(FakeSyncService):
    def status(self):
        return {
            "providers": [
                {"provider": "QRZ", "label": "QRZ", "configured": True},
                {"provider": "WRL", "label": "World Radio League", "configured": False},
                {"provider": "CLUBLOG", "label": "Club Log", "configured": False},
                {"provider": "LOTW", "label": "LoTW", "configured": True},
            ]
        }


def test_unconfigured_sources_are_skipped_without_distorting_progress():
    shared = {"lock": threading.Lock(), "active": 0, "max_active": 0}
    coordinator = ParallelSyncCoordinator(
        service_factory=lambda: PartiallyConfiguredService(shared),
        max_workers=4,
    )

    started = coordinator.start()
    assert started["total"] == 2
    assert started["providers"]["WRL"]["status"] == "skipped"

    done = wait_done(coordinator, started["job_id"])
    assert done["completed"] == 2
    assert done["progress"] == 100
    assert done["succeeded"] == 2
