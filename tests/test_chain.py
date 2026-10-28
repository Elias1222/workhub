"""接力：上一步的产物交给下一步，失败就整条跳过。"""
import shutil
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

    def test_handoff_step_waits_for_handback(self):
        """人工节点：交回结果之前后面一步一直等；交回后带着这段文字继续。"""

        def handoff(job):
            jobs.update_job(job, status="handed_off", note="复制到剪贴板并唤起应用",
                            ended=jobs.now_ts(), elapsed=0.1)

        seen = {}

        def second(job):
            seen["prompt"] = job["prompt"]
            jobs.update_job(job, status="succeeded", output="第二步做完了",
                            ended=jobs.now_ts(), elapsed=0.1)

        jobs.JOB_RUNNERS["codex"] = handoff
        jobs.JOB_RUNNERS["dsh"] = second
        _, made = jobs.dispatch_chain(
            [{"target": "codex", "prompt": "第一步"},
             {"target": "dsh", "prompt": "第二步"}])

        self.assertTrue(wait_for(lambda: jobs.get_job(made[0]["id"])["status"] == "handed_off"))
        time.sleep(0.3)
        self.assertEqual(jobs.get_job(made[1]["id"])["status"], "waiting")

        ok, message = jobs.handback_job(made[0]["id"], "WorkBuddy 里做出来的结果：三行提纲")
        self.assertTrue(ok, message)
        self.assertTrue(wait_for(lambda: jobs.get_job(made[1]["id"])["status"] == "succeeded"))
        self.assertIn("三行提纲", seen["prompt"])
        self.assertEqual(jobs.get_job(made[0]["id"])["status"], "succeeded")

    def test_handback_rejects_empty_and_wrong_state(self):
        ok, message = jobs.handback_job("nope", "有内容")
        self.assertFalse(ok)
        self.assertIn("不存在", message)

        job = jobs.new_job("codex", "还没交付的任务")
        ok, message = jobs.handback_job(job["id"], "有内容")
        self.assertFalse(ok)
        self.assertIn("人工交回", message)

        jobs.update_job(job, status="handed_off")
        ok, message = jobs.handback_job(job["id"], "   ")
        self.assertFalse(ok)
        self.assertIn("粘进来", message)

    def test_cancel_handed_off_step_skips_the_rest(self):
        def handoff(job):
            jobs.update_job(job, status="handed_off", note="等人工",
                            ended=jobs.now_ts(), elapsed=0.1)

        jobs.JOB_RUNNERS["codex"] = handoff
        jobs.JOB_RUNNERS["dsh"] = lambda job: None
        _, made = jobs.dispatch_chain(
            [{"target": "codex", "prompt": "第一步"},
             {"target": "dsh", "prompt": "第二步"}])

        self.assertTrue(wait_for(lambda: jobs.get_job(made[0]["id"])["status"] == "handed_off"))
        self.assertTrue(jobs.cancel_job(made[0]["id"]))
        self.assertTrue(wait_for(lambda: jobs.get_job(made[1]["id"])["status"] == "skipped"))
        self.assertIn("放弃", jobs.get_job(made[1]["id"])["error"])

    def test_runner_changes_are_recorded_and_passed_on(self):
        """真写文件：这一步的「改动」要能查出来，并交给下一步。"""
        dir_path = OUT_ROOT / "chain-touch"
        self.addCleanup(shutil.rmtree, dir_path, True)

        def writer(job):
            dir_path.mkdir(parents=True, exist_ok=True)
            (dir_path / "a.md").write_text("草稿\n", encoding="utf-8")
            jobs.update_job(job, status="succeeded", output="写了 a.md",
                            files=["chain-touch/a.md"], ended=jobs.now_ts(), elapsed=0.1)

        def rewriter(job):
            (dir_path / "a.md").write_text("草稿\n第二行\n", encoding="utf-8")
            (dir_path / "b.md").write_text("补充\n", encoding="utf-8")
            jobs.update_job(job, status="succeeded", output="改了 a.md，加了 b.md",
                            ended=jobs.now_ts(), elapsed=0.1)

        jobs.JOB_RUNNERS["codex"] = writer
        jobs.JOB_RUNNERS["dsh"] = rewriter
        _, made = jobs.dispatch_chain(
            [{"target": "codex", "prompt": "写草稿"},
             {"target": "dsh", "prompt": "接着改"}], outdir="chain-touch")

        self.assertTrue(wait_for(lambda: jobs.get_job(made[0]["id"])["status"] == "succeeded"))
        self.assertTrue(wait_for(lambda: jobs.get_job(made[1]["id"])["status"] == "succeeded"))

        first = jobs.get_job(made[0]["id"])
        self.assertTrue(wait_for(lambda: bool(jobs.get_job(made[0]["id"]).get("touched"))))
        first = jobs.get_job(made[0]["id"])
        self.assertEqual([c["path"] for c in first["touched"]], ["chain-touch/a.md"])
        self.assertEqual(first["touched"][0]["change"], "added")

        second = jobs.get_job(made[1]["id"])
        self.assertTrue(wait_for(lambda: bool(jobs.get_job(made[1]["id"]).get("touched"))))
        second = jobs.get_job(made[1]["id"])
        changes = {c["path"]: c["change"] for c in second["touched"]}
        self.assertEqual(changes.get("chain-touch/a.md"), "changed")
        self.assertEqual(changes.get("chain-touch/b.md"), "added")
        # 第二步的提示词里带的是「这一步实际改动」，而不是整个目录
        self.assertIn("这一步实际改动", second["prompt"])
        self.assertIn(str(OUT_ROOT / "chain-touch/a.md"), second["prompt"])

    def test_snapshot_diff_detects_add_change_remove(self):
        path = OUT_ROOT / "snap-demo"
        self.addCleanup(shutil.rmtree, path, True)
        path.mkdir(parents=True, exist_ok=True)
        (path / "keep.txt").write_text("v1", encoding="utf-8")
        (path / "gone.txt").write_text("bye", encoding="utf-8")
        before = jobs.snapshot_outdir(path)

        (path / "keep.txt").write_text("v1 plus more", encoding="utf-8")
        (path / "new.txt").write_text("hi", encoding="utf-8")
        (path / "gone.txt").unlink()
        after = jobs.snapshot_outdir(path)

        changes = {c["path"]: c for c in jobs.diff_snapshot(before, after)}
        self.assertEqual(changes["snap-demo/new.txt"]["change"], "added")
        self.assertEqual(changes["snap-demo/keep.txt"]["change"], "changed")
        self.assertEqual(changes["snap-demo/keep.txt"]["delta"], 10)
        self.assertEqual(changes["snap-demo/gone.txt"]["change"], "removed")

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
