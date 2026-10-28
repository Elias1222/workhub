"""接力：上一步的产物交给下一步，失败就整条跳过。"""
import threading
import time
import unittest

from workhub import jobs
from workhub.config import OUT_ROOT


def wait_for(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


class ChainTest(unittest.TestCase):
    def setUp(self):
        self._saved = dict(jobs.JOB_RUNNERS)
        jobs.JOB_RUNNERS.clear()
        jobs.JOBS.clear()

    def tearDown(self):
        jobs.JOB_RUNNERS.clear()
        jobs.JOB_RUNNERS.update(self._saved)
        jobs.JOBS.clear()

    def test_success_passes_files_and_answer_forward(self):
        def runner(job):
            jobs.update_job(job, status="succeeded", output="第一步答复：已经写好草稿",
                            files=["demo/a.md", "demo/b.txt"],
                            ended=jobs.now_ts(), elapsed=0.1)
        for target in ("codex", "dsh"):
            jobs.JOB_RUNNERS[target] = runner

        chain_id, made = jobs.dispatch_chain(
            [{"target": "codex", "prompt": "第一步：写草稿"},
             {"target": "dsh", "prompt": "第二步：润色"}])

        self.assertEqual(len(made), 2)
        self.assertEqual(made[0]["chain_id"], chain_id)
        self.assertEqual(made[0]["step"], 1)
        self.assertEqual(made[1]["steps_total"], 2)
        self.assertEqual(made[1]["depends_on"], made[0]["id"])
        self.assertTrue(wait_for(lambda: jobs.get_job(made[1]["id"])["status"] == "succeeded"))

        second = jobs.get_job(made[1]["id"])
        self.assertIn("【接力上下文", second["prompt"])
        self.assertIn("第一步答复：已经写好草稿", second["prompt"])
        self.assertIn(str(OUT_ROOT / "demo/a.md"), second["prompt"])
        self.assertIn("第二步：润色", second["prompt"])

    def test_failure_skips_the_rest(self):
        def bad(job):
            jobs.update_job(job, status="failed", error="第一步就炸了",
                            ended=jobs.now_ts(), elapsed=0.1)

        def should_not_run(job):
            raise AssertionError("上一步失败后，这一步不该跑")

        jobs.JOB_RUNNERS["codex"] = bad
        jobs.JOB_RUNNERS["dsh"] = should_not_run
        _, made = jobs.dispatch_chain(
            [{"target": "codex", "prompt": "第一步"},
             {"target": "dsh", "prompt": "第二步"}])

        self.assertTrue(wait_for(lambda: jobs.get_job(made[1]["id"])["status"] == "skipped"))
        second = jobs.get_job(made[1]["id"])
        self.assertIn("上一步", second["error"])
        self.assertIn("没有执行", second["error"])

    def test_second_step_waits_until_first_finishes(self):
        gate = threading.Event()

        def slow(job):
            gate.wait(5)
            jobs.update_job(job, status="succeeded", output="慢功告成",
                            ended=jobs.now_ts(), elapsed=1)

        def fast(job):
            jobs.update_job(job, status="succeeded", output="好了",
                            ended=jobs.now_ts(), elapsed=0)

        jobs.JOB_RUNNERS["codex"] = slow
        jobs.JOB_RUNNERS["dsh"] = fast
        _, made = jobs.dispatch_chain(
            [{"target": "codex", "prompt": "第一步"},
             {"target": "dsh", "prompt": "第二步"}])

        time.sleep(0.15)
        self.assertIn(jobs.get_job(made[0]["id"])["status"], ("running", "queued"))
        self.assertEqual(jobs.get_job(made[1]["id"])["status"], "waiting")
        gate.set()
        self.assertTrue(wait_for(lambda: jobs.get_job(made[1]["id"])["status"] == "succeeded"))

    def test_outdir_only_for_local_tools(self):
        def runner(job):
            jobs.update_job(job, status="succeeded", output="ok",
                            ended=jobs.now_ts(), elapsed=0)
        for target in ("codex", "dsh", "kimiweb"):
            jobs.JOB_RUNNERS[target] = runner

        _, made = jobs.dispatch_chain(
            [{"target": "kimiweb", "prompt": "https://example.com"},
             {"target": "codex", "prompt": "把正文整理成 md"}],
            outdir="chain-test")

        self.assertNotIn("outdir", made[0].get("params") or {})
        self.assertEqual((made[1].get("params") or {}).get("outdir"), "chain-test")

    def test_handoff_step_stops_the_chain(self):
        def handoff(job):
            jobs.update_job(job, status="handed_off", note="复制到剪贴板并唤起应用",
                            ended=jobs.now_ts(), elapsed=0.1)

        def should_not_run(job):
            raise AssertionError("人工接力之后不该继续")

        jobs.JOB_RUNNERS["codex"] = handoff
        jobs.JOB_RUNNERS["dsh"] = should_not_run
        _, made = jobs.dispatch_chain(
            [{"target": "codex", "prompt": "第一步"},
             {"target": "dsh", "prompt": "第二步"}])

        self.assertTrue(wait_for(lambda: jobs.get_job(made[1]["id"])["status"] == "skipped"))
        self.assertIn("人工接力", jobs.get_job(made[1]["id"])["error"])

    def test_cancel_waiting_step(self):
        def runner(job):
            jobs.update_job(job, status="succeeded", output="ok",
                            ended=jobs.now_ts(), elapsed=0)
        jobs.JOB_RUNNERS["codex"] = runner
        jobs.JOB_RUNNERS["dsh"] = runner
        gate = threading.Event()

        def hold(job):
            gate.wait(5)
            runner(job)

        jobs.JOB_RUNNERS["codex"] = hold
        _, made = jobs.dispatch_chain(
            [{"target": "codex", "prompt": "第一步"},
             {"target": "dsh", "prompt": "第二步"}])

        self.assertTrue(jobs.cancel_job(made[1]["id"]))
        self.assertEqual(jobs.get_job(made[1]["id"])["status"], "cancelled")
        gate.set()


if __name__ == "__main__":
    unittest.main()
