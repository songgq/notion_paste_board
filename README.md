# notion_paste_board v8

本版本调整：

- 软件名统一改为 `notion_paste_board`。
- 默认弹框宽度改为 `400`。
- 默认弹框透明度改为 `0.85`。
- 默认弹框自动关闭时间改为 `6000ms`。
- 设置窗口改成三个页签：`Notion`、`基础设置`、`弹框触发`。
- 保留 v7 能力：直连 Notion、音标显示、US/UK 内置发音、英文先弹框异步翻译、非英文右下角小图标。

## 运行

```bat
pythonw client.py
```

## 打包 EXE

```bat
build_exe.bat
```

生成位置：

```text
dist\notion_paste_board\notion_paste_board.exe
```

## 更新注意

运行新版前，请先从系统托盘退出旧版程序，避免多个客户端同时监听剪贴板。

Token 存储兼容旧版本：如果你之前已经保存过 Token，新版会先读取 `notion_paste_board_notion`，读取不到时会尝试读取旧的 `ClipboardAssistantNotion`。
