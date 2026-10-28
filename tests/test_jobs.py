"""任务层：建任务、落盘、交付目录收敛、产物列举。"""
import unittest

from workhub import config, jobs


class TestJobs(unittest.TestCase):
    def setUp(self):
        jobs.JOBS.clear()

    def test_new_job_defaults_and_public_shape(self):
        job = jobs.new_job("codex", "写个 hello", {"outdir": "demo"})
        self.assertTrue(job["id"].startswith("j"))
        self.assertEqual(job["status"], "queued")
        public = jobs.job_public(job)
        self.assertEqual(public["target"], "codex")
        self.assertEqual(public["name"], "Codex")
        for key in ("id", "prompt", "status", "started", "params"):
            self.assertIn(key, public)

    def test_update_job_persists_without_private_keys(self):
        job = jobs.new_job("dsh", "跑一下")
        jobs.update_job(job, status="succeeded", output="done", _cancel=False)
        self.assertTrue(config.JOBS_FILE.exists())
        raw = config.JOBS_FILE.read_text(encoding="utf-8")
        self.assertIn("succeeded", raw)
        self.assertNotIn("_cancel", raw, "私有字段不落盘")

    def test_get_job_and_list_jobs(self):
        job = jobs.new_job("muse", "出个片")
        self.assertIs(jobs.get_job(job["id"]), job)
        self.assertIsNone(jobs.get_job("nope"))
        self.assertEqual(len(jobs.list_jobs()), 1)

    def test_resolve_outdir_blocks_escape(self):
        self.assertIsNone(jobs.resolve_outdir(""))
        self.assertIsNone(jobs.resolve_outdir("   "))
        plain = jobs.resolve_outdir("image-1028")
        self.assertIsNotNone(plain)
        self.assertTrue(str(plain).startswith(str(config.OUT_ROOT)))
        nested = jobs.resolve_outdir("../../etc")
        if nested is not None:
            self.assertTrue(str(nested).startswith(str(config.OUT_ROOT)))

    def test_list_outdir_files_reports_relative_paths(self):
        outdir = jobs.resolve_outdir("listing-test")
        (outdir / "a.txt").write_text("hi", encoding="utf-8")
        files = jobs.list_outdir_files(outdir)
        self.assertEqual(files, ["listing-test/a.txt"])
        self.assertEqual(jobs.list_outdir_files(None), [])


if __name__ == "__main__":
    unittest.main()
