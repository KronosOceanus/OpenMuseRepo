# OpenMuse Web — 乐谱播放页

一个能**看谱 + 播放**的静态页面。零框架、零构建、零 npm、零后端。

```
index.html          页面本体（就这一个文件）
serve.py            本地预览服务（带 no-cache，避免改了看不到）
pieces.json         曲目清单
pieces/             MusicXML 文件放这
vendor/             AlphaTab / 音源 / 乐谱字体
```

## 跑起来

```bash
cd openmuse-web
python3 serve.py                # 默认 8080
# 打开 http://127.0.0.1:8080
```

> ⚠️ **必须用 http:// 打开，不能双击文件（file://）。**
> 浏览器对 file:// 下的字体加载和 fetch 有更严的限制，谱面会渲染不出来。

想看诊断日志就加 `?debug`：

```
http://127.0.0.1:8080/?debug
```

## 加一首曲子

```bash
python3 add-piece.py ~/Documents/MuseScore4/作曲/优纪.mscz youji "优纪"
```

**一条命令搞定** —— 转换、放进 `pieces/`、更新 `pieces.json`。

```
用法：python3 add-piece.py <乐谱文件> <id> [标题]

  <乐谱文件>   .mscx 或 .mscz；找不到时会去 ~/Documents/MuseScore4/ 下搜
  <id>         必须 ASCII（会进 URL，如 ?piece=youji）
  [标题]       显示名，省略则用 id
```

**手动做也可以，两步：**

```bash
# ① 转 MusicXML
"/Applications/MuseScore 4.app/Contents/MacOS/mscore" \
  -o pieces/youji.musicxml  /path/to/score.mscx

# ② 在 pieces.json 里加一行
{ "id": "youji", "title": "优纪", "file": "pieces/youji.musicxml" }
```

刷新页面，列表里就有了。

## 目录

```
index.html          页面本体（就这一个文件）
serve.py            本地预览服务（带 no-cache）
add-piece.py        加曲子（转换 + 修速度记号 + 更新清单）
fix-tempo.py        把非四分音符的速度记号换算成等价的四分音符
list-pieces.py      列出所有曲子的声部 / 音色 / 小节数
diff-musicxml.py    比两个 MusicXML → 差异清单（对比模式用）
merge-musicxml.py   把两份 MusicXML 拼成一份（不经过 MuseScore）
build-compare.py    一条命令做对照（转谱 → 修速度 → 配对 → 出清单）
make-demo-changes.py 造演示用的「改后」版本
pieces.json         曲目清单
pieces/             MusicXML
vendor/             AlphaTab / 音源 / 乐谱字体
```

## 依赖

| 文件 | 来源 | 为什么放本地 |
|---|---|---|
| `vendor/alphaTab.min.js` | `@coderline/alphatab@1.8.4` 的 `dist/alphaTab.min.js` | 不赌 CDN |
| `vendor/sonivox.sf2` | 同上的 `dist/soundfont/sonivox.sf2` | |
| `vendor/Bravura.woff2` | 同上的 `dist/font/Bravura.woff2` | |

升级 AlphaTab 时三个一起换，路径都是按包的实际结构来的。

---

## 对比模式

同一首曲子有两个版本（不同人扒的、或者你自己改的），左右并排看差异。
**改动处标红（原版）／标绿（改后）**，像 GitHub 的 diff，只是长在乐谱上。

### 怎么生成 —— 一条命令

```bash
python3 build-compare.py 版本A.mscz 版本B.mscz 对比id ["标题"]
```

它把整条流程串好了：

```
① 两边都转 MusicXML（.mscz/.mscx 走 MuseScore；已是 MusicXML 就直接用）
② **跑 fix-tempo.py**   ← 手工做时漏过这一步，结果一边播出来慢一倍
③ 声部按【名字】配对，出差异清单
④ 更新 pieces.json
⑤ 报告配上了哪些声部、哪些没配上、小节数是否一致
```

### 做演示样本

想造一份「改后」版本看效果（而不是拿真实的两个版本）：

```bash
python3 make-demo-changes.py pieces/曲子.musicxml pieces/曲子-mod.musicxml 8
```

自动挑「本来就有 ≥3 个音」的小节、沿全曲均匀分布、每处改 2-3 个音、
移调量控制在音域内。

### 声部是**按名字**配对的

不按下标。实测同一首曲子的不同编配版本声部数可以差很多 ——
`moonlight melody` 的三个版本分别是 **14 / 4 / 1** 个 part，
而它们共有的双簧管在两个文件里是**第 0 位和第 6 位**。
按下标比会拿双簧管去比长笛。

配不上的声部会列出来，跳过不比较。

### 页面上的行为

```
左栏 = file（原版）       右栏 = compareFile（改后）
改动处标红                对应处标绿

听：[🔊 原版] [· 改后]    ← 单选。同一时刻只有一个在响（见下）
点任意一栏的谱面           → 两边一起跳到那个位置
右下角 −  100%  +         → 缩放（两边联动）
右下角 ⇅                  → 自动滚动的开关
差异列表（默认折叠）        → 点一条跳到那一段；播放时那一行会高亮
```

### 为什么是「左右分栏」而不是「摞成一份谱」

摞叠要先把两个版本合成一份文件。**声部一多那份文件就出问题** ——
实测 11 个声部的曲子合并后 22 个 part，**MuseScore 直接段错误**
（退出码 139），转不出 MusicXML。

左右分栏只需要各自的 MusicXML，压根不用合并，而且**结构不同的两个版本
也能比**（小节数不一样也行，比到公共部分为止）。

> `merge-musicxml.py` 仍然留着（在 MusicXML 层拼接，不经过 MuseScore，
> 所以不会段错误）。想要摞叠视图的话它能用，只是页面上没做这个模式。

### 为什么「听」是单选，不能两个一起听

两个版本各是一个 AlphaTab 实例，**各有自己的音频时钟和缓冲**。
`apiA.play()` 和 `apiB.play()` 不是原子操作，中间差的那几毫秒消不掉 ——
同时播出来就是「乱七八糟」。而且就算对得齐，两个版本重叠着听也分不清谁是谁。

所以同一时刻只让一个响，切换时从**同一个 tick** 续上，A/B 对照是干净的。

---

## 排版

默认值是在**11 声部总谱**上实调出来的（不是猜的）：

```js
scale: 0.5        // 整体缩放
stretchForce: 1   // 小节拉伸力度 —— 「小节长度乱」主要看它
justifyLastSystem: true   // 最后一行也两端对齐
systemPaddingTop/Bottom: 60  // 行间距
trackStaffPaddingBetween: 24 // 声部间距
```

**调的时候不用改代码** —— 这些都有 URL 参数：

| 参数 | 作用 | 试试 |
|---|---|---|
| `stretch` | 小节拉伸 | `0.5` 挤左 / `1` / `2` / `3` 铺满 |
| `scale` | 整体缩放 | `0.5` / `1` / `1.2` |
| `syspad` | 行间距 | `16` / `30` / `60` |
| `staffpad` | 声部间距 | `5` / `16` / `24` / `36` |
| `bars` | 每行固定小节数 | `-1` 自动 / `4` / `8` |
| `justify` | 最后一行对齐 | `1` / `0` |
| `padx` `pady` | 页边距 | `16` / `24` / `40` |

```
http://127.0.0.1:8080/?piece=kyoutsuu&stretch=2&syspad=30&debug
```

`&debug` 会打出实际生效的值。

### 每首曲子单独的排版

`scale: 0.5` 是给总谱调的 —— **单声部钢琴曲用 0.5 会小得看不清**。
所以 `pieces.json` 里可以逐曲覆盖：

```json
{
  "id": "youji",
  "title": "优纪",
  "file": "pieces/youji.musicxml",
  "display": { "scale": 1.0, "systemPaddingTop": 24, "systemPaddingBottom": 24 }
}
```

不写 `display` 就用默认值。

### 但别指望像 MuseScore

```
AlphaTab     自研排版引擎，为「动态宽度 / 懒加载 / 网页交互」设计
MuseScore    成熟几十年的制谱引擎，目标是印刷级排版
```

**目标是「网页上看着舒服」，不是「印刷质量」。** 符干方向、连音线弧度、
密集和弦的偏移这些细节达不到 MuseScore 的水平。

**要印刷质量就分工：网页播放用 AlphaTab，出图出 PDF 用 MuseScore。**

---

## 播放光标

**AlphaTab 自带光标，不需要自己画。** 它在容器里插三个元素：

```
.at-cursors        光标层（absolute, z-index:1000）
  .at-cursor-bar   当前小节的色块
  .at-cursor-beat  当前拍的位置线
  .at-selection    选区（鼠标划播放范围时用）
```

**开关在 `player` 设置里，默认全是 `true`**（前提是 `enablePlayer: true`）：

```js
player: {
  enableCursor: true,              // 显示光标
  enableAnimatedBeatCursor: true,  // 拍光标平滑移动（false = 逐拍跳）
  enableElementHighlighting: true, // 高亮当前音符
}
```

**注意光标只在你按了播放之后才出现** —— 光是加载乐谱不会有。

**想改颜色/粗细必须在 CSS 里用 `!important`** —— AlphaTab 把样式写成内联的了：

```css
.at-cursor-bar  { background: rgba(74,158,255,.22) !important; }
.at-cursor-beat { background: #4a9eff !important; width: 3px !important; }
.at-highlight * { fill: #1f6fd0 !important; stroke: #1f6fd0 !important; }
```

**看不到光标时先加 `?debug`**，日志会打印：

```
光标[渲染后] .at-cursors=有  .at-cursor-bar=有  .at-cursor-beat=有
  bar  bg=rgba(74, 158, 255, 0.22)  display=block  240×80
  beat bg=rgb(74, 158, 255)  3×80
```

- **元素全「无」** → 光标没被建出来：检查 `enableCursor` / `enablePlayer`
- **元素有，但尺寸是 0×0 或颜色透明** → 是样式问题

---

## 踩过的坑（改这个页面之前先读）

全是实测出来的，不是猜的。**每一条都曾经让我以为是"功能没做对"，其实是环境或 API 细节。**

### 一、AlphaTab 相关

**① 音源必须用 `.sf2`，不能用 `.sf3`**

`.sf3` 是压缩格式，AlphaTab **静默拒绝** —— `soundFontLoad`、`soundFontLoaded`、`soundFontLoadFailed` **一个事件都不触发**，也没有任何报错。换成 `.sf2` 立刻正常（进度 15% → 100%）。

**② 位置事件叫 `playerPositionChanged`，不叫 `positionChanged`**

`AlphaTabApi` 上的事件是 **getter** 形式：

```ts
get playerPositionChanged(): IEventEmitterOfT<PositionChangedEventArgs>;
```

而 `positionChanged` 属于底层的 synth，**不在 API 上** —— 访问它是 `undefined`，`.on()` 直接抛 `TypeError`。

**这个异常会中断后面所有代码执行**（包括播放按钮的绑定），表现是**「点击毫无反应」，而且连日志都打不出来** —— 因为日志代码也在后面。

同理，`AlphaTabApi` 实际可用的事件只有这几个：

```
scoreLoaded  midiLoaded  soundFontLoad  soundFontLoaded  renderFinished
playerPositionChanged  playerStateChanged  playerReady  playerFinished
midiEventsPlayed  playbackRangeChanged  error
```

**③ `core.tracks` 默认只渲染第一个声部**

`@defaultValue null` —— **AlphaTab 只显示第一个 track**。单声部谱子（钢琴）看不出
来，但多乐器谱子会「听到所有乐器、只看到一件乐器的谱」。

```js
core: { tracks: 'all' }     // 'all' / 数字 / 数字数组
```

排查：`?debug` 时 `scoreLoaded` 会打出声部数。**谱里 11 个声部却只显示 1 行 = 这个坑。**

**④ 非四分音符的速度记号会慢一倍**

MuseScore 把「二分音符 = 80」导出成：

```xml
<metronome><beat-unit>half</beat-unit><per-minute>80</per-minute></metronome>
<sound tempo="160"/>
```

两处都对（half 80 == quarter 160），但 **AlphaTab 1.8.4 读 `<metronome>` 时忽略
`<beat-unit>`**，直接把 80 当成四分音符 BPM —— 慢一倍。

参考：[CoderLine/alphaTab#988](https://github.com/CoderLine/alphaTab/issues/988)

**`fix-tempo.py` 解决的**：把所有非四分音符的 metronome 换算成等价写法。
`add-piece.py` 会自动调用它。

**⑤ 字体目录要显式指定**

`core.fontDirectory` 默认是「**脚本所在目录**/font/」。我们的字体在 `vendor/` 下，不指定就找不到 → 谱面渲染成空白或乱码。

### 二、页面结构相关

**⑥ UI 控件的注册必须排在库事件之前**

一个库事件不存在就会抛异常，后面的代码全不执行。**把 `addEventListener` 放在最前面**，交互就永远可用。

**⑦ 每个事件注册都要单独包 `try/catch`**

```js
function reg(name, handler) {
  var ev = api[name]
  if (!ev || typeof ev.on !== 'function') { log('✗ ' + name + ' 不存在'); return }
  try { ev.on(handler); log('✓ ' + name) } catch (e) { log('✗ ' + name + ' ' + e.message) }
}
```

这样某个事件在当前版本里不存在时，**只跳过它**，而不是整页挂掉。而且它自己会报告哪个不存在 —— 排查时非常省事。

**⑧ `#score` 的 `min-height: 0` 不能省**

flex 子项的默认 `min-height` 是 `auto`，意味着**它不会小于内容高度**。谱面一长就撑开、把下面的控制条挤出屏幕。表现是「按钮看不见 / 点不到」。

### 三、环境相关

**⑨ 浏览器缓存会让"改了没生效"和"改了但无效"混淆**

`python -m http.server` **不发送任何缓存头**，浏览器会自己猜。结果是改完页面刷新还是旧的。

所以有了 `serve.py`（加 `Cache-Control: no-store`）和页面里的 `BUILD` 标记 —— **第一行日志就告诉你加载的是哪一版**。

**⑩ `http.server.TCPServer` 是单线程的**

一次只处理一个请求。浏览器会并发发好几个（HTML、JS、字体、音源），串行处理时后面的要排队。用 `http.server.ThreadingHTTPServer`。

（注意：`ThreadingHTTPServer` 在 `http.server` 里，**不在 `socketserver` 里**。）

**⑪ AlphaTab 不提供光标样式，得页面自己写**

`.at-cursors` / `.at-cursor-bar` / `.at-cursor-beat` 是几个**空 div**，
库不注入任何 CSS。不写样式就是透明的空盒子 —— 元素在、坐标也对，
**但完全看不见**。重写页面时漏掉这段，表现就是「没有光标」。

**⑫ `playerMode` 才是播放器的总开关（不是 `enablePlayer`）**

`playerMode` 默认 `Disabled`，而光标要不要建看的是
`playerMode !== Disabled && enableCursor`（见 min.js 的 `get _y()`）。

**⑬ `scrollMode` 一旦开过就关不干净**

实测：开一次自动滚动 → 再关 → 点任何按钮都往下滚，而且不是滚到光标。
改 `scrollMode` 或调 `stopScrolling` 都压不住。
**解法是不用它** —— `scrollMode` 恒为 0，自动滚动自己实现
（见 `scrollToCursor()`）。

**⑭ 两个实例是镜像的，处理器必须对称**

左右并排有两个 AlphaTab 实例，事件处理器是分别手写的。
**任何只写一边的逻辑都会漏** —— 实测「A 有自动滚动、B 没有」，
表现是「选原版会滚，选改后不滚」。
写完用工具对比两个 `regAll` 块。

**⑮ `tickPosition` 和 `play()` 都是 postMessage，别套在一起用**

```js
// ✗ 播放中这么写，play 会从 pause 的位置续上，把设的位置吞掉
if (was) pause(); tickPosition = t; if (was) play();

// ✓ 直接设就行
tickPosition = t;
```

表现是「播放中拖进度条卡一下但不动，继续从原处播」；
暂停时反而正常（因为没有 play 来覆盖）。

---

## 排查方法：让页面自己说话

**我看不到你的浏览器** —— 所以这个页面的设计原则是**把状态打出来**，而不是让人猜。

出问题时的顺序：

```
① 加 ?debug 打开诊断面板
② 看 BUILD 标记确认加载的是哪一版（排除缓存）
③ 看每个事件的 ✓/✗（定位到具体哪个 API 不存在）
④ 看点击有没有被记录（区分"事件没绑上"和"点了没反应"）
```

**这套方法把问题从「播放不了」一次缩到「`positionChanged` 不存在」。** 比盯着代码猜快得多。
