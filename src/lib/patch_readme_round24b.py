# -*- coding: utf-8 -*-
"""幂等给 README 追加 round24 后半程（§11.7 / §11.8）。

分两次写而不是回头改 §11.6，是因为这两条是**矩阵跑完之后**才在收口阶段
现场抓到的，属于新证据；把它们塞进旧小节会让"什么时候知道的"这条线索消失。

    python patch_readme_round24b.py
"""
import pathlib

README = pathlib.Path(__file__).parent / "scripts" / "cmlib" / "README.md"
MARK = "### 11.7 门禁自己被环境变量摆了一道"

SECTION = """

### 11.7 门禁自己被环境变量摆了一道（一次假 FAIL + 一次假 ALL PASSED）

收口阶段复跑门禁，同一份代码给出了两个相反的结论：

| 环境 | 结果 |
|---|---|
| `PYTHONIOENCODING=utf-8` | `[gate] ALL PASSED` |
| 裸 Windows 控制台（GBK/gb2312） | `[gate] FAILED —— 未通过的关卡: verify_natives` |

根因不在库，也不在 `verify_natives` 的核对逻辑 —— 它**核对通过了**，崩的是最后
那句"恭喜"：

```python
print("\\n[verify] \\u2713 符号存在性 / 实参个数 / 引擎常量 三项均与引擎声明一致")
# UnicodeEncodeError: 'gbk' codec can't encode character '\\u2713'
```

`'✓'`(U+2713) 不在 GBK 字符集里 → `print` 抛异常 → 脚本 rc=1 → `gate.py` 判这一关
FAILED。**「打印崩了」被门禁读成了「这一关没过」。**

更早一步，`gate.py` 自己也栽在同一个坑：它的第 1 关打印子进程输出时遇到
pytest 输出里的 `'ʧ'`(U+02A7)，直接 `UnicodeEncodeError` 退出，连关卡都没跑完。

还有一处**没报错但证据已经脏了**的问题：`gate.py` 用 `encoding="utf-8"` 解码子进程
输出，子进程却按 GBK 编码 —— 编解码口径不一致，中文被 `errors="replace"` 悄悄糊成
乱码，日志看着"有内容"，其实已经不可信。

**三处修法**

1. `gate.py` 给所有子进程显式传 `PYTHONIOENCODING=utf-8`，让子进程的编码与
   父进程的解码口径对齐；
2. 常驻入口脚本（`verify_natives.py` / `expected_asserts.py` / `matrix_daemon.py`）
   在 import 段后自卫：

   ```python
   for _s in (sys.stdout, sys.stderr):
       try:
           _s.reconfigure(errors="replace")
       except Exception:
           pass
   ```

   **只改 `errors` 策略，不改 `encoding`** —— 改成 utf-8 会让 GBK 控制台上的中文
   全变乱码，治了 A 病生 B 病。降级后 `✓` 显示成 `?`，信息量损失为零。
3. 新增 `test_console_encoding.py` 钉成**第 2 关**，含反向对照
   （`test_detector_actually_detects`）：合成样本必须被判为不安全、纯中文必须被放过。
   没有这条反向对照，探测函数一旦写坏就全表恒绿 —— 那正是"校验器自身要有校验器"
   要防的东西。

> **可复用判据：判定不能依赖与被测对象无关的环境细节。**
> round22 的教训是"别让次级判据插到 sentinel 前面"，这次是同一母题的另一面。
> 一个结论取决于调用者当时有没有 `export` 某个变量的门禁，**等于没有门禁**。
> 假 FAIL 比假 PASS 温和，但它同样会训练人去忽略红灯 —— 而红灯一旦被习惯性忽略，
> 下一次真的红灯也就没人看了。

### 11.8 「测的就是交付的」一直没有机器校验，这轮静默破了一次

round23 的收口报告里写着"构建后无 `.galaxy` 变更（测的就是交付的）"。
这轮才发现：**这条性质从来只靠纪律维持，仓库里没有任何检查在守它。**

现场翻出来的漂移：

```
CMLib.SC2Mod/README.md      117181 B   02:28:04   <- 构建时拷进去的，内容只到 round23
scripts/cmlib/README.md     127033 B   02:30:50   <- 源文件，§11 round24 在这里
```

`build_mod.py` 会把源 README 拷进 mod 目录，但 README 是在构建**之后**才被追加
round24 章节的 —— 于是交付的 `.SC2Mod` 里装着一份过期文档，而四件产物、三档矩阵
全都若无其事地绿着。README 不是代码，这次没有功能后果；但同样的时序错位发生在
`.galaxy` 上，结果就是**矩阵验的是旧库、交付的是新库**，且没有任何信号。

**修法**：新增 `check_artifact_freshness.py`，在真机矩阵开跑前做前置校验 ——
凡是进入产物的源文件（`scripts/cmlib/*.galaxy`、`selftest/*.galaxy`、`README.md`），
mtime 必须**早于**四件产物；否则 fail-closed 拒跑，并直接给出"先 rebuild"的指令。

> **可复用判据：写进报告的性质，必须有一个进程在守。**
> "构建后无源码变更"作为一句自觉遵守的纪律写了两轮，这轮就破了 ——
> 而且破得毫无声息。纪律的半衰期很短，检查没有。
"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if MARK in text:
        print("[readme] round24b 章节已存在，跳过")
        return 0
    README.write_text(text.rstrip() + SECTION, encoding="utf-8")
    print("[readme] 已追加 §11.7 / §11.8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
