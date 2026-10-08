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
diff-marks.py       比两个 MusicXML 的**记号**差异（力度/速度/连音线…）
add-mark-changes.py 给谱子注入记号改动（造测试数据）
make-demo-changes.py 造演示用的「改后」版本（改音高/删音/加音 三类轮流，
                     轮转各声部）
rebuild-compare.py  一条命令重造一份「三类差异合看」对照
                     （清空一个声部 → 三类改动 → 记号改动 → build-compare → 对账）
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

### 记号差异（音符之外的改动）

`diff-musicxml.py` **只比音符**。而记号改动完全不碰音符 —— 实测一份谱
注入 7 处记号改动（加力度、改速度、加连音线…），音符序列一个字节都没变，
音符对比的结论是「两个版本完全一致」。**那是误导** —— 用户会以为没问题。

所以记号单独一个脚本、单独一个 JSON：

```bash
python3 diff-marks.py A.musicxml B.musicxml --json pieces/曲子.marks.json
# 或者 build-compare.py 会自动产出，写进 pieces.json 的 "marks" 字段
```

结果在页面上表现为**小节左边缘一条紫色竖条** + 差异列表里单独一段。

**两类记号，两种比法：**

```
① 方向类：速度、力度、文字、渐强渐弱、踏板、排练号
   ⚠️ 这类**常常只写在某一个声部上** —— moonlight 的速度记号
      A 版写在双簧管、B 版写在长笛。分声部比会大量误报
      「A 有速度、B 没有」。
   ⟹ 跨声部合并后**按小节比**

② 音符挂载类：连音线、延音线、跳音、重音、延长号、装饰音、歌词、反复
   ⟹ 这些是声部自己的东西，**分声部比**
```

**为什么不画红绿框**：音符有坐标（音符头），记号没有 —— 力度挂在某拍上、
连音线跨几个音、文字挂在时间轴上，**没有一个可以框住的实体**。
所以用"小节边缘色条 + 列表文字"，含义是「这一小节还有别的变化，去列表看」。

**不比排版类**（页边距、行距、字体）—— 那是"怎么印"不是"音乐是什么"。

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

**⑯ 改了输出格式就必须重新生成产物**

`529589a` 改了 `diff-musicxml.py` 让它输出 `trackA`/`trackB`，但磁盘上的
`.diff.json` 还是旧格式（带 `track`）。于是页面里那句
`if (m.track == null) return`（按下标配对时代的残留守卫）一直没被触发，
**看着一切正常**。直到重新生成清单才爆出来 —— 表现是「完全没有标注」。

改输出格式后，**同步重新生成所有产物并验证一遍**。

**⑰ 只有记号改动时，音符差异是 0**

页面原来写着 `if (!diff.diffCount) { 显示"两个版本完全一致"; return }` ——
于是一份"只改了力度和连音线"的对照**根本不进对比模式**，直接显示"完全一致"。
判断条件要同时看音符差异和记号差异。

**⑱ AlphaTab 只读 `<metronome>`，忽略 `<sound tempo>`**

MusicXML 里速度有两处写法：

```xml
<metronome><beat-unit>quarter</beat-unit><per-minute>140</per-minute></metronome>
<sound tempo="140"/>          <!-- MuseScore 播放时用的值 -->
```

**AlphaTab 只认前者。** 而 MuseScore 导出的谱子里，变速点**不一定都带谱面记号**：

```
实测贝多芬第五：36 处 <sound tempo>，只有第 1 小节有 <metronome>
⟹ 整曲按第 1 小节的 194 BPM 播到底
⟹ 那段慢板实际 25~50 BPM，被播快了 4~8 倍
```

`fix-tempo.py` 会给缺失的 `<sound tempo>` 补一个 `<metronome>`。

⚠️ `<sound tempo>` 有两种放法，**第二种最容易漏**（正则只匹配 `<direction>` 会漏掉 31/36 处）：

```xml
① 包在 <direction> 里                    5 处
② 直接挂在 <measure> 下                  31 处
   <measure number="20"><sound tempo="140"/><note .../>
```

**⑲ tick 的取整方式必须和 AlphaTab 一致**

```python
int(round(onset / divisions * 960))    # ✗ 144/56*960 = 2468.57 → 2469
(onset * 960) // divisions             # ✓ → 2468（AlphaTab 给的就是这个）
```

差 1 个 tick，页面上「音高 + 位置精确匹配」就全部失手，只能落到兜底匹配。
实测因此漏掉过一处绿框。**跨系统传坐标时必须确认两边算法一致。**

**⑳ 声部重名要按顺序配对**

合奏谱里「乐队小提琴」出现两次很常见。用 `dict.setdefault(name, i)` 只记第一个 ——
第二个**静默消失**：不比、也不出现在 unmatched 里，报告只说「配上 7 个」。

实测世界献礼：两个「乐队小提琴」共 81 个音，其中 47 个从来没被比过。

正确做法是按名字分组、组内按顺序一一配对，重名时加序号后缀（`乐队小提琴 #1/#2`），
数量不一致时报警。

**㉑ 兜底匹配不能无限宽松**

「第一轮精确匹配失手 → 第二轮只按音高配」会把**移动了位置的音**当成未改动：

```
原版：C5@1拍  C#5@2拍  D5@3拍
改后：D5@1拍  C#5@2拍  B4@3拍      真实改动 2 处
旧逻辑：把原版 D5@3拍 和改后 D5@1拍 配成「没变」
        ⟹ 只报「删 C5、加 B4」，红框和绿框还落在不同拍上
```

第二轮必须带上**位置容差**（30 tick = 1/32 音符），只吸收舍入误差、不吸收真正位移。

**㉒ 防御性代码也会造成故障**

为了「宁可不标也不标错」，试过在兜底匹配里排掉有歧义的音高
（同一音高出现多次就全丢）。结果：改后有两个 F4，差异清单要标第一个，
**两个都被扔了，绿框一个都没有**。

而手里本来就有「最近的那个」这个信息，压根不需要这层防御。
**漏标比标错更难发现** —— 那次是靠肉眼逐格核对才看出来的。

**音符匹配的音高口径要「按小节选」，不能写死**

差异清单里的音高来自 MusicXML 的 `<pitch>`（**记谱音高**）。
AlphaTab 侧有两个字段，哪个等于它**随乐器变**：

```
无移调（长笛）            displayValue = realValue = 文件 ✅
移调乐器（小号 chrom=-2、   displayValue = 文件 ✅
          钟琴 octave-change=2）  realValue  = 文件 + 移调
⚠️ 神话2 的钢琴（无移调、   displayValue = 文件 − 12 ✗
   无八度谱号）             realValue  = 文件 ✅
```

写死认任何一个都会在"另一半乐器"上**静默失败** —— 一个框都不画，却没有任何报错。
（实测神话2：连音符差异的框也全缺，只是做记号框时才被发现。）

做法：**整小节**先用 displayValue 精确匹配；**一个都没中**才整小节换 realValue 重试。

```js
var basis = 'display'
var hits = pool.filter(… displayValue 匹配 …)
if (!hits.length) {
  var hReal = pool.filter(… realValue 匹配 …)
  if (hReal.length) { hits = hReal; basis = 'real' }
}
```

关键性质：**只在当前代码画出 0 个框时才改变行为** ⟹ 结构上不可能弄坏原本正常的情况。
（试过"每个音符两种都认"，对正常情况也放宽了、会撞车 —— 已回滚。）

诊断里会报出用了哪个口径：`displayValue 一个都没中 → 本小节改用 realValue 口径，命中 N`。

**挂载类记号改动会圈到具体音符上**

「第 21 小节 跳音：无 → 2」只说明**改了什么**，不说明改在**哪两个音符**上。
所以 `diff-marks.py` 额外输出 `noteMarks[]`，每个条目带着受影响音符的
`{pitch, tick, name}`；页面把它拼成和音符差异**同形**的条目，
复用同一套「音高 + 位置」匹配 —— 左栏画红、右栏画绿。

```
第 21 小节（小号（Bb））  重音 → A4 @ tick 480
第 21 小节（小号（Bb））  跳音 → A4 @ tick 480
第 21 小节（小号（Bb））  跳音 → F5 @ tick 480
```

⚠️ 位置口径**只有一处实现**（`diff-musicxml.measure_notes`，带 `keep_el=True`）——
tick 的取整方式差一点就会让匹配全部失手（见 ⑲）。`diff-marks.py` 直接
`importlib` 载入那个脚本复用，不另写一份。

⚠️ 只比「两边都在、且音高和位置都相同」的音符。被增删或移位的音符
由音符差异清单负责（那边已经画框了），在这里再报一遍会让同一个音符
被两套逻辑各画一次。

**㉓ 程序化滚动不能用 `behavior: 'smooth'`**

平滑滚动是异步动画，而 `bindScroll` 会在**每一帧**读到中间位置、当成"用户滚到了这里"
传给对面 —— 对面跟着一串虚假位置乱滚，抑制机制也追不上。

实测日志（点第 69 小节的记号条目）：

```
自动滚动：滚到第 69 小节（y=13680）
同步 A→B：小节 0 比例 -0.12 → 对面滚到 7     ← 才动了 1%
同步 A→B：小节 0 比例 -0.11 → 对面滚到 12
同步 A→B：小节 0 比例 -0.10 → 对面滚到 18
```

结果两栏显示的**不是同一小节**（截图里左 69、右 67）。改成 `scoreEl.scrollTop = y`
一步到位，同步读到的就是最终值。

（差异列表自己那处滚动仍可用 smooth —— 它不参与乐谱同步。）

**㉔ 点差异列表项是「定位」，不是「播放命令」**

原来写的是 `apiA/B.tickPosition = tick` 紧跟 `curApi().play()` —— **无条件起播**：

- 暂停时点一条 → 突然开始响，还得再按一次暂停
- 正在播时点一条 → 从那一小节的起点重头播，节奏被打断

改成走 `seekBothTo()`（点谱面用的就是它）：设位置本身不改播放状态 ——
正在播就从新位置续上，暂停就停在原地。

**㉕ 同一小节有多行时，高亮要认「用户点的那一行」**

`rowsByMeasure[小节]` 里可能同时有音符行和记号行。`syncDiffList` 原来固定取
`rows[0]` —— 于是「播放中点记号行」之后，播放位置没变、`onPosition` 继续触发，
高亮每次都被抢回 `rows[0]`（音符行），表现就是「点了记号行，列表自己跳到音符行」。

做法：`listCur.sel` 记住点过的那一行，同小节内优先保持它；
用户点的那行不在当前小节时（播放走过去了）自动回落到跟随播放。

**㉖ AlphaTab 的力度有两个坑（尚未修，仅记录）**

```
· Beat.dynamics / Note.dynamics 默认值是 DynamicValue.F（forte）——
  数据模型里**没有「没有力度记号」这个状态**。
  ⟹ 只要 hideDynamics 是 false，每个声部的第一个非休止拍**必然**冒出一个
     力度记号（哪怕谱上什么都没写）。实测 M02+03 左栏长笛第 69 小节那个 f。

· 导入器有一个字段 this.qo（初值 F），遇到 <dynamics> 才改写，**从不重置**。
  文件按 part 顺序解析 ⟹ 前面声部的一个 pp 会**泄漏给后面所有声部**。
  实测 M02+03：中提琴/小军鼓那一个 pp 泄漏成 9 个声部的全程 pp。
```

另外 `hideDynamics` 默认 true，遇到 `**任何一个**` `<dynamics>` 就永久置 false ——
所以哪怕谱里只有一处力度记号，整个乐谱的力度显示都会被打开。

`hideDynamics` **只管力度记号**（`EffectDynamics` 一处检查），
渐强（`EffectCrescendo`）、跳音、文字记号都不受影响。

**㉗ 「算出来的路径 + 写/删」必须先确认它不等于输入文件**

踩过：重造对照的脚本把改后版写到了 `pieces/{id}.musicxml`，
而 `src`（原版）**就是** `pieces/{id}.musicxml` —— 先覆盖，`finally` 里的清理又把它删了。

后果不是报错，而是 `build-compare` 拿"改后版"和"改后版"比 →
**静默报「0 处差异、0 个空缺」**，看起来像跑通了，其实什么都没比。

⟹ 临时产物一律写临时目录；清理前再确认一次路径不等于任何输入。

**㉘ 一个脚本里既当输入名又当输出名的两个 id 必须显式分开**

`rebuild-compare.py` 原来只有一个 `id` 参数，我传了基础曲目 id（`m0203`），
而 `build-compare` 是拿 pid 当**产物名**的 —— 于是：

```
· 产物成了 m0203-a/-b/.diff.json/.marks.json（应该是 m0203-all-*）
· pieces.json 里【单曲条目 m0203】被覆盖成了对照条目
```

同样**不报错**：单曲页还在，只是变成了一个"对照"，而真正的对照缺文件。

⟹ 基础曲目 id 和对照条目 id 分开两个参数，且断言 `cmp_id != base`。

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
