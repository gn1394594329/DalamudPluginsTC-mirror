"""把 DalamudPluginsTC 的 repo.json 下載連結，從 GitHub API 資產網址換成 release 直接下載網址。

原版連結 https://api.github.com/repos/<owner>/<repo>/releases/assets/<id> 只接受
Accept: application/octet-stream；只送 application/zip 的 Dalamud 會拿到 415。
release 直接下載網址（browser_download_url）不看 Accept，任何 Dalamud 都能下載。

用法：
    python rewrite_links.py --repo upstream.json --releases releases.json --out repo.json

releases.json 可以是 release 陣列，或 `gh api --paginate --slurp` 產生的「每頁一個陣列」。
除了下載連結以外，所有欄位與順序都原樣保留。
"""

import argparse
import json
import os
import sys
import tempfile

LINK_FIELDS = ("DownloadLinkInstall", "DownloadLinkUpdate", "DownloadLinkTesting")
API_PREFIX = "https://api.github.com/repos/"
DOWNLOAD_PREFIX = "https://github.com/"


class RewriteError(Exception):
    pass


def parse_asset_id(url):
    """API 資產網址回傳 asset id，其他網址或非字串回傳 None。"""
    if not isinstance(url, str) or not url.startswith(API_PREFIX):
        return None
    parts = url[len(API_PREFIX):].split("/")
    if len(parts) != 5 or parts[2] != "releases" or parts[3] != "assets":
        return None
    asset_id = parts[4]
    if not (asset_id.isascii() and asset_id.isdigit()):
        return None
    return int(asset_id)


def build_asset_map(releases):
    """建立 asset id → browser_download_url 對照表。"""
    if not isinstance(releases, list):
        raise RewriteError("release 清單必須是陣列")
    pages = releases if releases and all(isinstance(p, list) for p in releases) else [releases]

    mapping = {}
    for page in pages:
        for release in page:
            if not isinstance(release, dict):
                raise RewriteError("release 清單裡有不是物件的項目")
            assets = release.get("assets") or []
            if not isinstance(assets, list):
                raise RewriteError(f"release {release.get('tag_name')!r} 的 assets 不是陣列")
            for asset in assets:
                asset_id = asset.get("id") if isinstance(asset, dict) else None
                url = asset.get("browser_download_url") if isinstance(asset, dict) else None
                if not isinstance(asset_id, int) or isinstance(asset_id, bool):
                    raise RewriteError(f"release {release.get('tag_name')!r} 有缺少 id 的 asset")
                if not isinstance(url, str) or not url.startswith(DOWNLOAD_PREFIX):
                    raise RewriteError(f"asset {asset_id} 的 browser_download_url 不正確：{url!r}")
                mapping[asset_id] = url
    return mapping


def rewrite(plugins, asset_map):
    """就地改寫 plugins 的下載連結。

    回傳 (改寫數, 找不到對應的清單)。找不到對應的連結保持原樣，讓其他插件照常更新；
    但若一個都對應不到，代表 release 清單整個有問題，直接報錯。
    """
    if not isinstance(plugins, list) or not plugins:
        raise RewriteError("repo.json 必須是非空陣列")

    rewritten = 0
    unmapped = []
    for plugin in plugins:
        if not isinstance(plugin, dict):
            raise RewriteError("repo.json 裡有不是物件的項目")
        for field in LINK_FIELDS:
            asset_id = parse_asset_id(plugin.get(field))
            if asset_id is None:
                continue
            url = asset_map.get(asset_id)
            if url is None:
                unmapped.append((plugin.get("InternalName", "?"), field, plugin[field]))
                continue
            plugin[field] = url
            rewritten += 1

    if unmapped and rewritten == 0:
        raise RewriteError(f"{len(unmapped)} 個 API 連結全部找不到對應的 release asset")
    return rewritten, unmapped


def dump(plugins):
    """輸出格式跟上游一致：2 格縮排、不跳脫中文、結尾換行。"""
    return json.dumps(plugins, ensure_ascii=False, indent=2) + "\n"


def load_json(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def write_atomic(path, text):
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="上游 repo.json")
    parser.add_argument("--releases", required=True, help="GitHub API 的 release 清單 JSON")
    parser.add_argument("--out", required=True, help="輸出的 repo.json")
    args = parser.parse_args(argv)

    try:
        plugins = load_json(args.repo)
        asset_map = build_asset_map(load_json(args.releases))
        rewritten, unmapped = rewrite(plugins, asset_map)
    except (OSError, json.JSONDecodeError, RewriteError) as e:
        print(f"錯誤：{e}", file=sys.stderr)
        return 1

    in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    for name, field, url in unmapped:
        prefix = "::warning::" if in_actions else "警告："
        print(f"{prefix}{name} 的 {field} 找不到對應的 release asset，保留原連結：{url}", file=sys.stderr)

    write_atomic(args.out, dump(plugins))
    print(f"{len(plugins)} 個插件，改寫 {rewritten} 個連結，{len(unmapped)} 個找不到對應")
    return 0


if __name__ == "__main__":
    sys.exit(main())
