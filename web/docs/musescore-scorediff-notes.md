# MuseScore 的谱面对比（ScoreDiff）是怎么实现的

> 这份笔记为了**以后想做「结构位移对齐」时不用重新拉源码**。
> 下面每一条都对着源码看过的，没看过的会明确标注。

## 来源

```
仓库  musecore/MuseScore
文件  libmscore/scorediff.cpp   55335 字节 / 1459 行
      libmscore/scorediff.h      5168 字节
      mscore/scorecmp/scorediffmodel.{h,cpp}   （UI 两个 list model）
ref   3.x           sha 0a5ce400
拉取  https://raw.githubusercontent.com/musescore/MuseScore/3.x/libmscore/scorediff.cpp
日期  2026-10-09
```

**⚠️ 不要把这些源码拷进本仓库。** MuseScore 是 GPLv2，而本仓库的许可不一定相容 ——
需要看代码就按上面 URL 现拉。这份笔记只记**思路**和**必要的小段摘录**。

**⚠️ 已知版本差异**：这份是 **MuseScore 3.4 / 3.x** 的。
**MuseScore 4 里这个功能没有了**（社区帖标题就是 "Compare scores missing from View menu"，
但正文被 Cloudflare 拦了 403，所以**「删掉」还是「没移植」我没能核实**）。

---

## 一、总流程（`ScoreDiff::update()`，第 792 行）

```cpp
void ScoreDiff::update()
{
    XmlWriter xml1(_s1), xml2(_s2);          // ← 导出时**同时**记下「元素 ↔ 标签名」的有序列表
    QString mscx1(scoreToMscx(_s1, xml1));
    QString mscx2(scoreToMscx(_s2, xml2));

    _textDiffs = MscxModeDiff().mscxModeDiff(mscx1, mscx2);   // ① 文本 diff（含"位移修正"）

    if (!_textDiffOnly) {
        makeDiffs(mscx1, mscx2, xml1, xml2, _textDiffs, _diffs);  // ② 映回谱面元素
        processMarkupDiffs();        // ③ 四步合并
        mergeInsertDeleteDiffs();
        mergeElementDiffs();
        editPropertyDiffs();
        std::stable_sort(_diffs.begin(), _diffs.end(), positionSort);  // ④ 按**乐谱位置**排序
    }
}
```

**⟹ 一句话：**导出成文本 → 文本 diff → 双游标映回元素 → 合并 → 按乐谱位置排序**。**

## 二、diff 算法用的是 **dtl**，不是 diff_match_patch

```cpp
#include "dtl/dtl.hpp"
...
dtl::Diff<QStringRef, std::vector<QStringRef>> diff(lines1, lines2);
diff.compose();
```

**⚠️ 更正**：我最初从头文件里 `TextDiff` 的注释
"A structure similar to Diff from diff_match_patch" 就断言它用 diff_match_patch ——
**那是推测当结论，错的**。实际用的是 **dtl**（Diff Template Library）。
（这条留着提醒自己：**注释里的类比不等于依赖**。）

## 三、「行号 → 谱面元素」靠**双游标同步重解析**（这是最值得记的一招）

```cpp
// ScoreDiff.cpp 里的 makeDiffs（第 748 行）
static void makeDiffs(const QString& mscx1, const QString& mscx2,
                      const XmlWriter& xml1, const XmlWriter& xml2,
                      const std::vector<TextDiff>& textDiffs, std::vector<BaseDiff*>& diffs)
{
    TextDiffParser p1(0);  p1.makeDiffs(mscx1, xml1.elements(), textDiffs, diffs);
    TextDiffParser p2(1);  p2.makeDiffs(mscx2, xml2.elements(), textDiffs, diffs);
    std::stable_sort(diffs.begin(), diffs.end(), lineNumberSort);
    // 再把 ctx / before 从"上一个"补全，滤掉 EQUAL 和 ContextChange
}
```

`TextDiffParser::makeDiffs`（第 531 行）的核心：

```cpp
QXmlStreamReader r(mscx);                 // ← 把同一份 MSCX 文本**再解析一遍**
r.readNext();
auto textDiff    = textDiffs.begin();
auto nextElement = elements.begin();      // ← 导出时记下的 (元素, 标签名) 有序列表

while (!r.atEnd()) {
    // ① 光标推进：跳过已经过去的差异区间
    while (textDiff != end && textDiff->end[iScore] < r.lineNumber()) { ...; ++textDiff; }

    // ② 当前 token 在不在"本侧"的差异里
    bool saveDiff = !insideDiffTag()
                 && (textDiff->type == DELETE || textDiff->type == INSERT)
                 && iScore == iDiffScore;

    if (r.isStartElement()) {
        // ③ **解析顺序 == 写入顺序**，所以两个游标天然对得上
        if (nextElement != end && nextElement->second == r.name())
            newElement = (nextElement++)->first;
        ++tagLevel;
        tagIsElement.push_back(newElement);   // 栈：当前元素是谁
    }

    BaseDiff* diff = handleToken(r, newElement, saveDiff);
    if (diff) { diff->ctx[iScore] = contextsStack.back();
                diff->before[iScore] = lastElementEnded; ... }
    ...
    r.readNext();
}
```

**⟹ 要点：**

```
XmlWriter 写 MSCX 时**按顺序**记下「第 N 个标签 ↔ 哪个 ScoreElement」
读的时候用 QXmlStreamReader 走同一份文本 —— 顺序必然一致
  ⟹ 两个游标同步推进，标签就自然对上了元素
  ⟹ 再用 r.lineNumber() 跟 TextDiff 的 [start, end] 行号区间比，判断"当前元素在不在差异里"
  ⟹ tagIsElement 栈维护"现在挂在哪个元素上"
```

**⟹ 可复用的思路：**不靠行号查表，靠「同一份文本 + 同一套顺序 + 再走一遍」** ——
**顺序一致性替掉了映射表**。

## 四、它的「结构对齐」= 差异块边界的**位移修正**（`MscxModeDiff`）

**行 diff 的固有毛病：会把 XML 元素切成两半**，于是差异块里的标签不成对、
挂到错误的元素上。它的修法分两步：

```cpp
// 第 208 行
int MscxModeDiff::adjustSemanticsMscxOneDiff(std::vector<TextDiff>& diffs, int index)
{
    ...
    readMscx(diff->text[iScore], extraTags);   // 找出这块里**多出来**的标签（未配对的）

    if (extraTags.empty()) return index;       // 干净，不用修

    // 用「多余标签占的行数」当平移量，上下各试一次
    int lines = lastEndExtra->line - firstEndExtra->line + 1;
    if (assessShiftDiff(diffs, extraTags, index,  lines)) return performShiftDiff(diffs, index,  lines);
    lines = -(lastStartExtra->line - firstStartExtra->line + 1);
    if (assessShiftDiff(diffs, extraTags, index, lines)) return performShiftDiff(diffs, index, lines);
    return index;
}
```

- **`assessShiftDiff`**（第 274 行）：把差异块边界平移 N 行后，那些多余标签
  **能否被相邻块抵消** —— 要求 `diffChunk == nextChunk`，且首尾多余标签的名字能与
  相邻块的首尾一一配对。
- **`performShiftDiff`**（第 337 行）：真的把那 N 行文本从差异块挪进相邻的 EQUAL 块，
  并**逐块修正行号**，必要时插入一个新的 EQUAL 块。

**⟹ 所以它的"结构"粒度是 **XML 标签**，不是小节/乐句。**
**⟹ 插了一小节导致后面整体错位时，它只能靠"标签边界吸附"救回一部分，
   并不能把 A 的第 12 小节和 B 的第 13 小节认成"同一个小节"。**

顺带一个诚实的实现状态：`case DiffType::REPLACE:` 那里挂着
`// TODO: split a REPLACE diff, though they should not be here`。

## 五、数据模型（`scorediff.h`）

```cpp
enum class DiffType { EQUAL, INSERT, DELETE, REPLACE };
enum class ItemType { ELEMENT, PROPERTY, MARKUP, CONTEXTCHANGE };

struct TextDiff {                  // 纯文本层，只有行号
    DiffType type;
    QString  text[2];
    int      start[2];             // 两份文本里的起始行号
    int      end[2];
    void merge(const TextDiff&);
};

struct BaseDiff {                  // 映回元素之后的基类
    DiffType type;
    const TextDiff*    textDiff;
    const ScoreElement* ctx[2];    // 上下文元素（这处差异属于谁）
    const ScoreElement* before[2]; // 前一个元素
    virtual ItemType itemType() const = 0;
    virtual Fraction afrac(int score) const;   // 在乐谱里的**时刻**（定位/高亮用）
};

struct ElementDiff  : BaseDiff { const ScoreElement* el[2]; };  // 元素增删
struct PropertyDiff : BaseDiff { Pid pid; };                    // 属性变化
struct MarkupDiff   : BaseDiff { QString name; QVariant info; };// 标记
struct ContextChange: BaseDiff { };                             // 临时，用来续上下文
```

**UI 侧两个 list model（`mscore/scorecmp/scorediffmodel.h`）：**
```
RawScoreDiffModel  原始文本 diff 的每一行（skipEqual 可开关）
ScoreDiffModel     合并后的 BaseDiff 条目
```

## 六、和本项目（OpenMuse 对照页）的对比

| | MuseScore ScoreDiff | 我们 |
|---|---|---|
| diff 算法 | **dtl** 行 diff | 自己写的**结构化配对** |
| 对齐粒度 | **XML 标签**（靠边界平移吸附） | **声部名 + 小节序号 + 音高/tick** |
| 行号↔元素 | 双游标同步重解析 | 不涉及（本来就在结构层） |
| 插入一小节 | 行号错位，靠平移修正**部分**救回 | **完全不影响后面** |
| 差异表示 | `ctx` / `before` 上下文指针 + 4 类 | 扁平（小节 + 声部 + 音高/tick） |
| 覆盖面 | **更广**（任何序列化差异都能发现：力度、时值、装饰音…） | 窄一些（音符增删改 + 记号） |
| 重名声部 | 靠文本位置 | 按 `<part-name>` 配对，重名加序号 |
| 移调乐器 | 文本层面对得上就行 | 记谱音高，`displayValue`/`realValue` 按小节选口径 |

**⟹ 它不是"没有结构对齐"，而是**在标签粒度上对齐**；我们在**小节/音符粒度**上对齐。
  两者的"结构"不是一回事。**

## 七、以后可以借鉴的三点

```
① 双游标同步重解析
   如果要把"我们的差异"和"外部工具的输出"对上（比如 MuseScore 自己导出的标注），
   这个"顺序一致性替掉映射表"的思路能省掉一整套坐标映射。

② 边界吸附 —— 我们那条搁置的「结构位移对齐」的方向提示
   我们已有 TICK_TOL = 30 吸收取整误差；但对"整拍/整小节位移"没有任何处理。
   它的做法提示了一个通用套路：
     先用粗糙的 diff 拿到候选差异 → 再用**边界吸附**把差异收敛到结构单元上
   对应到我们这边，结构单元是「小节 + 声部 + 音高」，不是 XML 标签。

③ 差异挂 ctx / before
   我们现在是「第 N 小节 + 声部」的扁平列表。
   要表达"这一段整体移高了八度"这类**模式**，上下文指针比 pitch 列表更有表达力。
```

## 八、没核实的地方（别当成结论用）

```
· MuseScore 4 里这个功能是删除还是尚未移植 —— 没核实（社区帖 403）
· scorediff.h 里 UI 那部分的 .cpp（scorediffmodel.cpp）没读
· TextDiffParser::handleToken 的内部（第 624~737 行）没逐行读，
  只看了它被调用处的上下文
· 3.x 分支后续版本是否有改动 —— 只看了 3.x 当时的 sha 0a5ce400
```
