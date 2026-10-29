# DalamudPluginsTC-mirror

[ffxiv-tc-port/DalamudPluginsTC](https://github.com/ffxiv-tc-port/DalamudPluginsTC) 的 `repo.json` 轉換版，只把下載連結換成 release 直接下載網址，讓 XIVTCLauncher 內建的 Dalamud 也能安裝、更新插件。插件檔一樣從 ffxiv-tc-port 的 release 下載。

非官方，與 ffxiv-tc-port 無關。

## 使用方式

在 Dalamud「實驗性功能」→ 自訂插件庫加入：

```
https://raw.githubusercontent.com/gn1394594329/DalamudPluginsTC-mirror/main/repo.json
```

並停用原版網址。已從原版網址安裝的插件，要解除安裝後從這裡重裝。

## 同步

GitHub Actions 每 3 小時同步一次原版 `repo.json`。
