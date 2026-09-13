"""命名规则引擎：全部为纯函数，不做任何文件或网络 IO。"""

from __future__ import annotations

import re
from typing import Sequence

from .model import SequenceRecord

# 比较停用词、种下标记词时统一剥离的首尾标点
PUNCT_CHARS = ".,;:()[]{}\"'*?<>/\\|`"

_KEEP_ACCESSION = re.compile(r"[^A-Za-z0-9._-]")
_DROP_SPECIES = re.compile(r"[|,;:()\[\]{}\"'*?<>/\\`\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")
_UNDERSCORES = re.compile(r"_+")

# 命中即终止扫描：这些词之后的内容不属于物种名
STOPWORDS = frozenset({
    "chloroplast", "mitochondrion", "mitochondrial", "mitogenome", "plastid",
    "plastome", "genome", "complete", "partial", "sequence", "sequences",
    "chromosome", "contig", "scaffold", "segment", "isolate", "voucher",
    "clone", "strain", "cultivar", "cv", "breed", "culture", "gene", "genes",
    "mrna", "rrna", "trna", "dna", "rna", "its", "whole", "shotgun", "wgs",
    "assembly", "chromosome-level", "complete-genome", "genomic", "dna-sequence",
})

# 命中即吸收进物种名（种下等级标记），随后至多再吸收一个词
INFRASPECIFIC = frozenset({
    "sp", "spp", "cf", "aff", "subsp", "ssp", "var", "fo", "f", "nothosubsp",
    "x", "×",
})

# 伪装成物种名的前缀，须整词剥离。
# 按长度降序排列只是防御性写法：当前 8 个前缀两两之间不存在前缀关系
# （'tpa:' 的第 4 个字符是 ':'，'tpa_exp:' 是 '_'），因此顺序目前不影响正确性，
# 但将来若加入真正互为前缀的项（如 'tpa' 与 'tpa_exp:'），此排序即成为必要。
DISGUISE_PREFIXES = tuple(sorted(
    ("unverified:", "mag:", "tpa:", "tpa_exp:", "tpa_inf:", "tpa_asm:",
     "tsa:", "wgs:"),
    key=len,
    reverse=True,
))

# 物种名最多由几个词构成。硬上限，防止畸形 header 吞掉整行。
# 注意：标记词分支在同一次迭代内会追加 2 个词，因此该分支也必须重复检查此上限，
# 否则实际上界会变成 5（历史上曾有此缺陷）。
MAX_SPECIES_TOKENS = 4


def sanitize_accession(text: str) -> str:
    """登录号规范化：删除空白与非法字符，**保留句点**（版本号分隔符）。"""
    stripped = text.replace("\u3000", "").replace(" ", "")
    return _KEEP_ACCESSION.sub("", stripped)


def sanitize_species(text: str) -> str:
    """物种名规范化：空白转下划线、杂交符号转 x、**删除句点**与其余标点。"""
    text = text.replace("\u3000", " ").replace("\t", " ")
    text = _SPACES.sub(" ", text).strip()
    text = text.replace("×", "x").replace(".", "")
    text = _DROP_SPECIES.sub("", text)
    text = text.replace(" ", "_")
    return _UNDERSCORES.sub("_", text).strip("_")


def _compare_key(token: str) -> str:
    """生成用于和停用词/标记词比较的键：转小写并剥离首尾标点。"""
    return token.strip(PUNCT_CHARS).lower()


def extract_species_from_header(header_body: str) -> tuple[str, tuple[str, ...]]:
    """从 FASTA header（已剥离登录号）或 GenBank DEFINITION 中提取物种名。

    返回 (species_raw, warnings)。species_raw 保持原始拼写，规范化由
    sanitize_species() 负责。提取失败时 species_raw 为空串。
    """
    warnings: list[str] = []

    # 步骤 1：归一化空白
    text = header_body.replace("\u3000", " ").replace("\t", " ").strip()
    # 杂交符号两侧统一补空格：使 '×tragus'、'Salsola×tragus' 与规范写法 'Salsola × tragus'
    # 等价。否则粘连形式下 × 既非大写字母也非可吸收的小写词，扫描直接终止，会静默只取到属名。
    text = _SPACES.sub(" ", text.replace("×", " × ")).strip()

    # 步骤 2：循环剥离伪装前缀
    changed = True
    while changed:
        changed = False
        lowered = text.lower()
        for prefix in DISGUISE_PREFIXES:
            if not lowered.startswith(prefix):
                continue
            remainder = text[len(prefix):]
            if remainder and not remainder[0].isspace():
                continue
            text = remainder.lstrip()
            warnings.append(f"已剥离伪装前缀 {prefix}")
            changed = True
            break

    # 步骤 3：分词
    tokens = [token for token in text.split(" ") if token]

    # 步骤 4：顺序扫描
    absorbed: list[str] = []
    index = 0
    while index < len(tokens) and len(absorbed) < MAX_SPECIES_TOKENS:
        token = tokens[index]
        key = _compare_key(token)
        if not key:
            index += 1
            continue
        if key in STOPWORDS:
            break
        if key in INFRASPECIFIC:
            absorbed.append(token)
            index += 1
            if index < len(tokens) and len(absorbed) < MAX_SPECIES_TOKENS:
                follower = tokens[index]
                follower_key = _compare_key(follower)
                if (follower_key
                        and follower_key not in STOPWORDS
                        and follower_key not in INFRASPECIFIC):
                    absorbed.append(follower)
                    index += 1
            break
        if token[0].isupper():
            absorbed.append(token)
            index += 1
            continue
        if len(absorbed) < 2 and token[0].isalpha():
            absorbed.append(token)
            index += 1
            continue
        break

    # 步骤 5：判据
    if not absorbed:
        return "", ("无法从 header 提取物种名",)
    return " ".join(absorbed), tuple(warnings)


NAMING_MODES = ("keep", "accession", "species", "accession_species")


def species_key(record: SequenceRecord) -> str:
    """物种名分组键：用于统计同物种的序列条数。物种名缺失时回退为登录号基号。

    **不再参与流水号分配**：流水号的判据已改为"渲染出的基名是否会撞车"
    （见 :func:`build_name_map`），物种是否重复与文件名是否重名是两回事。本函数作为
    公开 API 保留（已有调用方与测试），将来按物种分组统计时仍会用到。
    """
    key = sanitize_species(record.species)
    if key:
        return key
    return sanitize_accession(record.accession_base) or "unknown"


def render_name(record: SequenceRecord, mode: str,
                serial: int | None = None) -> str:
    """按命名模式渲染序列名；serial 非 None 时追加流水号后缀。"""
    if mode not in NAMING_MODES:
        raise ValueError(f"未知命名模式: {mode}")
    if mode == "keep":
        return record.accession

    accession = sanitize_accession(record.accession)
    species = sanitize_species(record.species)

    if mode == "accession":
        name = accession or species
    elif mode == "species":
        name = species or accession
    else:  # accession_species
        name = "_".join(part for part in (accession, species) if part)

    # 基名为空时不追加流水号：否则名字会变成 "_1"→"1" 这种真值，
    # 使 build_name_map 的 `name or f"sequence_{index}"` 兜底永不生效，
    # 产出 "1"/"2" 这类可能与真实名撞车的裸数字名。
    if serial is not None and name:
        name = f"{name}_{serial}"
    return _UNDERSCORES.sub("_", name).strip("_")


def build_name_map(records: Sequence[SequenceRecord],
                   mode: str) -> dict[SequenceRecord, str]:
    """两遍处理：先统计同名基名条数，再按出现顺序分配流水号。

    **判据是"渲染出的基名是否会撞车"，不是"物种是否重复"**（用户使用后提出的调整）。

    旧实现按 :func:`species_key` 计数，与命名模式无关：``accession_species`` 模式下
    同一物种有 3 条不同登录号的序列，第 3 条就被写成 ``MZ230595.1_..._3``——用户实际
    拿到过这种名字。流水号的唯一目的是防止**最终文件名撞车**，而 ``accession_species``
    / ``accession`` 模式的基名以登录号开头，登录号天然唯一 ⇒ 基名不可能重复 ⇒ 加号
    纯属多余。

    ``species`` 模式必须继续发号：基名里没有登录号，两条同物种记录渲染出的基名完全
    相同，不发号就真的会重名（下游建树工具会报错或静默丢序列）。

    真正的撞车（去重关闭时同一登录号出现两次，或两条记录渲染出同一基名）仍然会发号。
    """
    # 模式校验必须在 keep 短路之前：否则空批次下非法模式会被静默当成 keep，
    # 与 render_name 的「未知 mode 抛 ValueError」契约不一致。
    if mode not in NAMING_MODES:
        raise ValueError(f"未知命名模式: {mode}")
    if mode == "keep":
        return {}

    # 计数键 = 不带流水号的渲染基名（render_name 在 serial=None 时不做任何追加）。
    counts: dict[str, int] = {}
    for record in records:
        base = render_name(record, mode)
        counts[base] = counts.get(base, 0) + 1

    seen: dict[str, int] = {}
    mapping: dict[SequenceRecord, str] = {}
    for index, record in enumerate(records, start=1):
        base = render_name(record, mode)
        serial = None
        if counts[base] > 1:
            seen[base] = seen.get(base, 0) + 1
            serial = seen[base]
        name = render_name(record, mode, serial)
        mapping[record] = name or f"sequence_{index}"
    return mapping
