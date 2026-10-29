import contextlib
import io
import json
import os
import tempfile
import unittest

import rewrite_links as rl

API = "https://api.github.com/repos/ffxiv-tc-port/DalamudPluginsTC/releases/assets/"
DL = "https://github.com/ffxiv-tc-port/DalamudPluginsTC/releases/download/"


def release(tag, *assets):
    return {
        "tag_name": tag,
        "assets": [{"id": i, "browser_download_url": f"{DL}{tag}/{name}"} for i, name in assets],
    }


def plugin(name, install, update=None, **extra):
    p = {"Name": name, "InternalName": name, "DownloadLinkInstall": install}
    p["DownloadLinkUpdate"] = install if update is None else update
    p.update(extra)
    return p


class ParseAssetIdTest(unittest.TestCase):
    def test_api_asset_url(self):
        self.assertEqual(rl.parse_asset_id(API + "678693764"), 678693764)

    def test_other_urls_are_ignored(self):
        for url in (
            DL + "Accountant-v7.25.0.24/Accountant.zip",
            "https://api.github.com/repos/o/r/releases/latest",
            "https://api.github.com/repos/o/r/releases/assets/12/extra",
            "https://api.github.com/repos/o/r/releases/assets/",
            "https://api.github.com/repos/o/r/releases/assets/12a",
            "https://api.github.com/repos/o/r/releases/assets/１２",
            "",
            None,
            123,
        ):
            with self.subTest(url=url):
                self.assertIsNone(rl.parse_asset_id(url))


class BuildAssetMapTest(unittest.TestCase):
    def test_flat_list(self):
        m = rl.build_asset_map([release("A-v1", (1, "A.zip")), release("B-v1", (2, "B.zip"))])
        self.assertEqual(m, {1: DL + "A-v1/A.zip", 2: DL + "B-v1/B.zip"})

    def test_paged_list_from_gh_slurp(self):
        m = rl.build_asset_map([[release("A-v1", (1, "A.zip"))], [release("B-v1", (2, "B.zip"))]])
        self.assertEqual(set(m), {1, 2})

    def test_release_without_assets(self):
        self.assertEqual(rl.build_asset_map([{"tag_name": "x", "assets": []}, {"tag_name": "y"}]), {})

    def test_empty(self):
        self.assertEqual(rl.build_asset_map([]), {})
        self.assertEqual(rl.build_asset_map([[]]), {})

    def test_malformed_input_raises(self):
        for bad in (
            {"message": "Not Found"},
            [1, 2],
            [{"tag_name": "x", "assets": "nope"}],
            [{"tag_name": "x", "assets": [{"browser_download_url": DL + "x/a.zip"}]}],
            [{"tag_name": "x", "assets": [{"id": True, "browser_download_url": DL + "x/a.zip"}]}],
            [{"tag_name": "x", "assets": [{"id": 1, "browser_download_url": API + "1"}]}],
        ):
            with self.subTest(bad=bad), self.assertRaises(rl.RewriteError):
                rl.build_asset_map(bad)


class RewriteTest(unittest.TestCase):
    def test_rewrites_install_update_and_testing(self):
        plugins = [plugin("A", API + "1", DownloadLinkTesting=API + "2")]
        n, unmapped = rl.rewrite(plugins, {1: DL + "A-v1/A.zip", 2: DL + "A-t/A.zip"})
        self.assertEqual((n, unmapped), (3, []))
        self.assertEqual(plugins[0]["DownloadLinkInstall"], DL + "A-v1/A.zip")
        self.assertEqual(plugins[0]["DownloadLinkUpdate"], DL + "A-v1/A.zip")
        self.assertEqual(plugins[0]["DownloadLinkTesting"], DL + "A-t/A.zip")

    def test_other_fields_and_key_order_are_preserved(self):
        p = plugin("A", API + "1", AssemblyVersion="7.25.0.1", Tags=["x"], LastUpdate=1793285537)
        p["DownloadLinkTesting"] = None
        plugins = [p]
        before = list(p)
        rl.rewrite(plugins, {1: DL + "A-v1/A.zip"})
        self.assertEqual(list(plugins[0]), before)
        self.assertEqual(plugins[0]["Tags"], ["x"])
        self.assertEqual(plugins[0]["LastUpdate"], 1793285537)
        self.assertIsNone(plugins[0]["DownloadLinkTesting"])

    def test_non_api_links_are_untouched(self):
        plugins = [plugin("A", DL + "A-v1/A.zip")]
        self.assertEqual(rl.rewrite(plugins, {}), (0, []))
        self.assertEqual(plugins[0]["DownloadLinkInstall"], DL + "A-v1/A.zip")

    def test_unmapped_link_is_kept_and_reported(self):
        plugins = [plugin("A", API + "1"), plugin("B", API + "9")]
        n, unmapped = rl.rewrite(plugins, {1: DL + "A-v1/A.zip"})
        self.assertEqual(n, 2)
        self.assertEqual(
            unmapped,
            [("B", "DownloadLinkInstall", API + "9"), ("B", "DownloadLinkUpdate", API + "9")],
        )
        self.assertEqual(plugins[1]["DownloadLinkInstall"], API + "9")

    def test_nothing_mapped_raises(self):
        with self.assertRaises(rl.RewriteError):
            rl.rewrite([plugin("A", API + "1")], {})

    def test_bad_repo_shape_raises(self):
        for bad in ({}, [], [1], None):
            with self.subTest(bad=bad), self.assertRaises(rl.RewriteError):
                rl.rewrite(bad, {})


class DumpTest(unittest.TestCase):
    def test_round_trip_matches_upstream_format(self):
        text = '[\n  {\n    "Name": "記帳",\n    "Tags": [\n      "a"\n    ],\n    "N": 1\n  }\n]\n'
        self.assertEqual(rl.dump(json.loads(text)), text)


class MainTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def path(self, name):
        return os.path.join(self.dir.name, name)

    def write(self, name, data):
        with open(self.path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rl.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_writes_rewritten_repo(self):
        self.write("up.json", [plugin("中文插件", API + "1")])
        self.write("rel.json", [[release("A-v1", (1, "A.zip"))]])
        code, out, _ = self.run_main(
            "--repo", self.path("up.json"), "--releases", self.path("rel.json"), "--out", self.path("repo.json")
        )
        self.assertEqual(code, 0)
        self.assertIn("改寫 2 個連結", out)
        with open(self.path("repo.json"), "rb") as f:
            raw = f.read()
        self.assertNotIn(b"\r\n", raw)
        self.assertIn("中文插件".encode(), raw)
        self.assertEqual(json.loads(raw)[0]["DownloadLinkInstall"], DL + "A-v1/A.zip")

    def test_error_leaves_existing_output_untouched(self):
        with open(self.path("repo.json"), "w", encoding="utf-8") as f:
            f.write("previous")
        self.write("up.json", [plugin("A", API + "1")])
        self.write("rel.json", {"message": "API rate limit exceeded"})
        code, _, err = self.run_main(
            "--repo", self.path("up.json"), "--releases", self.path("rel.json"), "--out", self.path("repo.json")
        )
        self.assertEqual(code, 1)
        self.assertIn("錯誤", err)
        with open(self.path("repo.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "previous")

    def test_invalid_json_is_an_error(self):
        with open(self.path("up.json"), "w", encoding="utf-8") as f:
            f.write("404: Not Found")
        self.write("rel.json", [])
        code, _, _ = self.run_main(
            "--repo", self.path("up.json"), "--releases", self.path("rel.json"), "--out", self.path("repo.json")
        )
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(self.path("repo.json")))


if __name__ == "__main__":
    unittest.main()
