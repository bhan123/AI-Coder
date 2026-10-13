"""Content pack loading.

A *content pack* holds everything that changes when you point this engine at a
different topic: which sources to poll, which keywords the pre-filter rewards,
what the columns are called, which phrases are banned, and which visual
templates the cover renderer may pick from.

The engine code never hardcodes any of that. It asks a :class:`ContentPack`.

Layout of a pack directory::

    packs/<name>/
        pack.toml        # identity, columns, platform skeletons, delivery
        keywords.toml    # pre-filter keyword groups, source credibility/heat
        quality.toml     # banned phrases, risky topics, title patterns
        style.toml       # visual template registry
        prompts/
            scoring.md
            factual_draft.md
            editorial_voice.md
            weekly_recap.md

Every field is validated on load, so a malformed pack fails immediately at
startup with a precise message rather than producing subtly wrong articles
hours later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import tomllib
from types import MappingProxyType
from typing import Any

# The engine ships four platform bodies; only WeChat has automated delivery.
PLATFORMS: tuple[str, ...] = ("wechat", "xiaohongshu", "toutiao", "zhihu")

REQUIRED_PROMPTS: tuple[str, ...] = (
    "scoring",
    "factual_draft",
    "editorial_voice",
)
OPTIONAL_PROMPTS: tuple[str, ...] = ("weekly_recap",)

_PACK_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,38}[a-z0-9]")
_HEX_COLOR_PATTERN = re.compile(r"#[0-9A-Fa-f]{6}")
_VISUAL_LAYOUTS = frozenset({"split", "verdict", "takeaway"})


class PackError(ValueError):
    """A content pack is missing, malformed, or internally inconsistent."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_table(data: Any, where: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PackError(f"{where} must be a table")
    return data


def _require_text(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PackError(f"{where}.{key} must be a non-empty string")
    return value.strip()


def _optional_text(data: dict[str, Any], key: str, where: str) -> str:
    value = data.get(key, "")
    if not isinstance(value, str):
        raise PackError(f"{where}.{key} must be a string")
    return value.strip()


def _require_str_tuple(data: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise PackError(f"{where}.{key} must be an array of non-empty strings")
    return tuple(item.strip() for item in value)


def _require_int(
    data: dict[str, Any],
    key: str,
    where: str,
    *,
    default: int | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if key not in data and default is not None:
        value: Any = default
    else:
        value = data.get(key, default)
    # bool is an int subclass; reject it explicitly.
    if type(value) is not int:
        raise PackError(f"{where}.{key} must be an integer")
    if minimum is not None and value < minimum:
        raise PackError(f"{where}.{key} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise PackError(f"{where}.{key} must be <= {maximum}")
    return value


def _read_toml(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise PackError(f"pack file is missing: {path.name}")
        return {}
    if path.is_symlink():
        raise PackError(f"pack file must not be a symlink: {path.name}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise PackError(f"pack file is unreadable: {path.name}") from error
    except tomllib.TOMLDecodeError as error:
        raise PackError(f"pack file is not valid TOML: {path.name} ({error})") from error


# ---------------------------------------------------------------------------
# Pack components
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeywordGroup:
    """One scoring dimension's keyword lists and its baseline score."""

    base: int
    cn: frozenset[str]
    en: frozenset[str]

    def score(self, text: str) -> int:
        """Count Chinese and English hits on top of the baseline, capped 1-10."""
        lowered = text.lower()
        hits = sum(1 for word in self.cn if word in text)
        hits += sum(1 for word in self.en if word in lowered)
        return max(1, min(10, self.base + hits))


@dataclass(frozen=True)
class HeatRule:
    """Maps a raw popularity metric onto a 1-10 heat score.

    ``thresholds`` is descending: the first threshold the value clears wins.
    ``combine`` optionally folds several raw fields together, e.g. ModelScope
    downloads plus stars weighted 100x.
    """

    fields: tuple[str, ...]
    weights: tuple[int, ...]
    thresholds: tuple[tuple[int, int], ...]
    floor: int

    def score(self, raw: dict[str, Any]) -> int:
        combined = 0
        for name, weight in zip(self.fields, self.weights, strict=True):
            try:
                combined += int(raw.get(name) or 0) * weight
            except (TypeError, ValueError):
                continue
        for threshold, points in self.thresholds:
            if combined >= threshold:
                return points
        return self.floor


@dataclass(frozen=True)
class ColumnSpec:
    """An editorial column: its name, routing rules, and writing guide."""

    name: str
    guide: str
    match_sources: tuple[str, ...] = ()
    match_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class VisualTemplate:
    name: str
    layout: str
    background: str
    accent: str
    foreground: str


@dataclass(frozen=True)
class ContentPack:
    """Everything topic-specific the engine needs."""

    name: str
    root: Path
    description: str

    # --- discovery ---
    source_credibility: MappingProxyType
    credibility_prefixes: tuple[tuple[str, int], ...]
    credibility_default: int
    heat_rules: MappingProxyType
    heat_prefixes: tuple[tuple[str, int], ...]
    heat_default: int

    # --- pre-filter scoring ---
    keyword_groups: MappingProxyType
    clickbait_words: frozenset[str]
    clickbait_penalty_per_hit: int
    clickbait_penalty_max: int
    score_weights: MappingProxyType
    recency_tiers: tuple[tuple[int, float], ...]
    novelty_base_dated: int
    novelty_base_undated: int

    # --- selection balance ---
    research_sources: frozenset[str]
    practical_sources: frozenset[str]
    practical_prefixes: tuple[str, ...]
    max_research_per_batch: int

    # --- editorial ---
    columns: tuple[ColumnSpec, ...]
    default_column: str
    brief_task: str
    brief_checklist: tuple[str, ...]
    platform_skeletons: MappingProxyType
    platform_min_chars: MappingProxyType

    # --- quality gates ---
    banned_promises: tuple[str, ...]
    risky_topics: tuple[str, ...]
    clickbait_patterns: tuple[str, ...]
    synthetic_title_patterns: tuple[re.Pattern[str], ...]
    title_min_chars: int
    title_max_chars: int
    body_min_chars: int
    max_exclamations: int
    max_title_question_marks: int

    # --- visuals ---
    visual_templates: MappingProxyType

    # --- prompts ---
    prompts: MappingProxyType

    def prompt_path(self, name: str) -> Path:
        """Absolute path to a prompt file, for engines that pass paths around."""
        if name not in self.prompts:
            raise PackError(f"pack '{self.name}' has no prompt '{name}'")
        return self.root / "prompts" / f"{name}.md"

    def column_for(self, *, source: str, text: str, override: str = "") -> str:
        """Route an item to a column. An LLM-supplied override always wins."""
        if override and override.strip():
            return override.strip()
        lowered_source = source.lower()
        lowered_text = text.lower()
        for column in self.columns:
            if any(token in lowered_source for token in column.match_sources):
                return column.name
            if any(token.lower() in lowered_text for token in column.match_keywords):
                return column.name
        return self.default_column

    def column_guide(self, name: str) -> str:
        for column in self.columns:
            if column.name == name:
                return column.guide
        for column in self.columns:
            if column.name == self.default_column:
                return column.guide
        return ""

    def credibility_for(self, source: str) -> int:
        if source in self.source_credibility:
            return int(self.source_credibility[source])
        for prefix, points in self.credibility_prefixes:
            if source.startswith(prefix):
                return points
        return self.credibility_default

    def heat_for(self, source: str, raw: dict[str, Any]) -> int:
        rule = self.heat_rules.get(source)
        if rule is not None:
            return rule.score(raw if isinstance(raw, dict) else {})
        for prefix, points in self.heat_prefixes:
            if source.startswith(prefix):
                return points
        return self.heat_default

    def is_practical_source(self, source: str) -> bool:
        return source in self.practical_sources or source.startswith(
            self.practical_prefixes
        )


# ---------------------------------------------------------------------------
# Section readers
# ---------------------------------------------------------------------------


def _read_keywords(data: dict[str, Any]) -> tuple[
    MappingProxyType,
    frozenset[str],
    int,
    int,
    MappingProxyType,
    tuple[tuple[str, int], ...],
    int,
    MappingProxyType,
    tuple[tuple[str, int], ...],
    int,
    MappingProxyType,
    tuple[tuple[int, float], ...],
    int,
    int,
]:
    groups_raw = _require_table(data.get("groups", {}), "keywords.groups")
    if not groups_raw:
        raise PackError("keywords.groups must define at least one dimension")
    groups: dict[str, KeywordGroup] = {}
    for key, raw in groups_raw.items():
        where = f"keywords.groups.{key}"
        table = _require_table(raw, where)
        groups[key] = KeywordGroup(
            base=_require_int(table, "base", where, default=5, minimum=1, maximum=10),
            cn=frozenset(_require_str_tuple(table, "cn", where)),
            en=frozenset(
                word.lower() for word in _require_str_tuple(table, "en", where)
            ),
        )

    clickbait = _require_table(data.get("clickbait", {}), "keywords.clickbait")
    clickbait_words = frozenset(_require_str_tuple(clickbait, "words", "keywords.clickbait"))
    penalty_per_hit = _require_int(
        clickbait, "penalty_per_hit", "keywords.clickbait", default=2, minimum=0
    )
    penalty_max = _require_int(
        clickbait, "penalty_max", "keywords.clickbait", default=6, minimum=0
    )

    cred = _require_table(data.get("credibility", {}), "keywords.credibility")
    cred_scores = _require_table(cred.get("sources", {}), "keywords.credibility.sources")
    credibility = {}
    for key, value in cred_scores.items():
        if type(value) is not int or not 1 <= value <= 10:
            raise PackError(
                f"keywords.credibility.sources.{key} must be an integer 1-10"
            )
        credibility[str(key)] = value
    cred_prefixes = _read_prefix_scores(
        cred.get("prefixes", []), "keywords.credibility.prefixes"
    )
    cred_default = _require_int(
        cred, "default", "keywords.credibility", default=5, minimum=1, maximum=10
    )

    heat = _require_table(data.get("heat", {}), "keywords.heat")
    heat_rules: dict[str, HeatRule] = {}
    for key, raw in _require_table(heat.get("sources", {}), "keywords.heat.sources").items():
        where = f"keywords.heat.sources.{key}"
        table = _require_table(raw, where)
        fields = _require_str_tuple(table, "fields", where)
        if not fields:
            raise PackError(f"{where}.fields must not be empty")
        weights_raw = table.get("weights", [1] * len(fields))
        if not isinstance(weights_raw, list) or not all(
            type(w) is int for w in weights_raw
        ):
            raise PackError(f"{where}.weights must be an array of integers")
        if len(weights_raw) != len(fields):
            raise PackError(f"{where}.weights must match the length of fields")
        thresholds_raw = table.get("thresholds", [])
        if not isinstance(thresholds_raw, list) or not thresholds_raw:
            raise PackError(f"{where}.thresholds must be a non-empty array")
        thresholds: list[tuple[int, int]] = []
        for entry in thresholds_raw:
            if (
                not isinstance(entry, list)
                or len(entry) != 2
                or type(entry[0]) is not int
                or type(entry[1]) is not int
            ):
                raise PackError(f"{where}.thresholds entries must be [value, score]")
            if not 1 <= entry[1] <= 10:
                raise PackError(f"{where}.thresholds scores must be 1-10")
            thresholds.append((entry[0], entry[1]))
        if any(
            thresholds[i][0] <= thresholds[i + 1][0] for i in range(len(thresholds) - 1)
        ):
            raise PackError(f"{where}.thresholds must be in descending value order")
        heat_rules[str(key)] = HeatRule(
            fields=fields,
            weights=tuple(weights_raw),
            thresholds=tuple(thresholds),
            floor=_require_int(table, "floor", where, default=1, minimum=1, maximum=10),
        )
    heat_prefixes = _read_prefix_scores(heat.get("prefixes", []), "keywords.heat.prefixes")
    heat_default = _require_int(
        heat, "default", "keywords.heat", default=5, minimum=1, maximum=10
    )

    weights_table = _require_table(data.get("weights", {}), "keywords.weights")
    if not weights_table:
        raise PackError("keywords.weights must define the scoring weights")
    weights: dict[str, float] = {}
    for key, value in weights_table.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise PackError(f"keywords.weights.{key} must be a number")
        if not 0 <= float(value) <= 1:
            raise PackError(f"keywords.weights.{key} must be between 0 and 1")
        weights[str(key)] = float(value)
    unknown = set(weights) - set(groups) - {"heat", "credibility", "novelty"}
    if unknown:
        raise PackError(
            "keywords.weights references unknown dimensions: "
            + ", ".join(sorted(unknown))
        )
    total = sum(weights.values())
    if abs(total - 1.0) > 0.001:
        raise PackError(f"keywords.weights must sum to 1.0 (got {total:.3f})")

    recency = _require_table(data.get("recency", {}), "keywords.recency")
    tiers_raw = recency.get("tiers", [])
    if not isinstance(tiers_raw, list) or not tiers_raw:
        raise PackError("keywords.recency.tiers must be a non-empty array")
    tiers: list[tuple[int, float]] = []
    for entry in tiers_raw:
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or type(entry[0]) is not int
            or not isinstance(entry[1], (int, float))
            or isinstance(entry[1], bool)
        ):
            raise PackError("keywords.recency.tiers entries must be [max_age_days, multiplier]")
        tiers.append((entry[0], float(entry[1])))
    novelty_dated = _require_int(
        recency, "novelty_base_dated", "keywords.recency", default=7, minimum=1, maximum=10
    )
    novelty_undated = _require_int(
        recency, "novelty_base_undated", "keywords.recency", default=5, minimum=1, maximum=10
    )

    return (
        MappingProxyType(groups),
        clickbait_words,
        penalty_per_hit,
        penalty_max,
        MappingProxyType(credibility),
        cred_prefixes,
        cred_default,
        MappingProxyType(heat_rules),
        heat_prefixes,
        heat_default,
        MappingProxyType(weights),
        tuple(tiers),
        novelty_dated,
        novelty_undated,
    )


def _read_prefix_scores(raw: Any, where: str) -> tuple[tuple[str, int], ...]:
    if not isinstance(raw, list):
        raise PackError(f"{where} must be an array of [prefix, score] pairs")
    pairs: list[tuple[str, int]] = []
    for entry in raw:
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not entry[0].strip()
            or type(entry[1]) is not int
            or not 1 <= entry[1] <= 10
        ):
            raise PackError(f"{where} entries must be [prefix, score 1-10]")
        pairs.append((entry[0].strip(), entry[1]))
    return tuple(pairs)


def _read_quality(data: dict[str, Any]) -> dict[str, Any]:
    gates = _require_table(data.get("gates", {}), "quality.gates")
    patterns_raw = _require_str_tuple(data, "synthetic_title_patterns", "quality")
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns_raw:
        try:
            compiled.append(re.compile(pattern))
        except re.error as error:
            raise PackError(
                f"quality.synthetic_title_patterns contains invalid regex: {pattern} ({error})"
            ) from error
    return {
        "banned_promises": _require_str_tuple(data, "banned_promises", "quality"),
        "risky_topics": _require_str_tuple(data, "risky_topics", "quality"),
        "clickbait_patterns": _require_str_tuple(data, "clickbait_patterns", "quality"),
        "synthetic_title_patterns": tuple(compiled),
        "title_min_chars": _require_int(gates, "title_min_chars", "quality.gates", default=8, minimum=1),
        "title_max_chars": _require_int(gates, "title_max_chars", "quality.gates", default=40, minimum=2),
        "body_min_chars": _require_int(gates, "body_min_chars", "quality.gates", default=100, minimum=1),
        "max_exclamations": _require_int(gates, "max_exclamations", "quality.gates", default=5, minimum=0),
        "max_title_question_marks": _require_int(
            gates, "max_title_question_marks", "quality.gates", default=2, minimum=0
        ),
    }


def _read_style(data: dict[str, Any]) -> MappingProxyType:
    templates_raw = _require_table(data.get("templates", {}), "style.templates")
    if not templates_raw:
        raise PackError("style.templates must define at least one template")
    templates: dict[str, VisualTemplate] = {}
    for key, raw in templates_raw.items():
        where = f"style.templates.{key}"
        table = _require_table(raw, where)
        layout = _require_text(table, "layout", where)
        if layout not in _VISUAL_LAYOUTS:
            raise PackError(
                f"{where}.layout must be one of {sorted(_VISUAL_LAYOUTS)}"
            )
        colors = {}
        for field_name in ("background", "accent", "foreground"):
            value = _require_text(table, field_name, where)
            if not _HEX_COLOR_PATTERN.fullmatch(value):
                raise PackError(f"{where}.{field_name} must be a #RRGGBB hex color")
            colors[field_name] = value
        templates[str(key)] = VisualTemplate(name=str(key), layout=layout, **colors)
    return MappingProxyType(templates)


def _read_columns(data: dict[str, Any]) -> tuple[tuple[ColumnSpec, ...], str]:
    columns_raw = data.get("columns", [])
    if not isinstance(columns_raw, list) or not columns_raw:
        raise PackError("pack.columns must be a non-empty array of tables")
    columns: list[ColumnSpec] = []
    for index, raw in enumerate(columns_raw):
        where = f"pack.columns[{index}]"
        table = _require_table(raw, where)
        columns.append(
            ColumnSpec(
                name=_require_text(table, "name", where),
                guide=_require_text(table, "guide", where),
                match_sources=tuple(
                    token.lower()
                    for token in _require_str_tuple(table, "match_sources", where)
                ),
                match_keywords=_require_str_tuple(table, "match_keywords", where),
            )
        )
    names = [column.name for column in columns]
    if len(set(names)) != len(names):
        raise PackError("pack.columns names must be unique")

    default_column = _optional_text(data, "default_column", "pack") or names[0]
    if default_column not in names:
        raise PackError(
            f"pack.default_column '{default_column}' is not one of the defined columns"
        )
    return tuple(columns), default_column


def _read_platforms(data: dict[str, Any]) -> tuple[MappingProxyType, MappingProxyType]:
    skeletons_raw = _require_table(data.get("platform_skeletons", {}), "pack.platform_skeletons")
    missing = [name for name in PLATFORMS if name not in skeletons_raw]
    if missing:
        raise PackError(
            "pack.platform_skeletons is missing: " + ", ".join(missing)
        )
    unknown = set(skeletons_raw) - set(PLATFORMS)
    if unknown:
        raise PackError(
            "pack.platform_skeletons has unknown platforms: " + ", ".join(sorted(unknown))
        )
    skeletons = {}
    for name in PLATFORMS:
        value = skeletons_raw[name]
        if not isinstance(value, str) or not value.strip():
            raise PackError(f"pack.platform_skeletons.{name} must be a non-empty string")
        skeletons[name] = value.strip()

    min_chars_raw = data.get("platform_min_chars", {})
    min_chars_table = _require_table(min_chars_raw, "pack.platform_min_chars")
    min_chars = {}
    for name in PLATFORMS:
        value = min_chars_table.get(name, 600)
        if type(value) is not int or value < 0:
            raise PackError(
                f"pack.platform_min_chars.{name} must be a non-negative integer"
            )
        min_chars[name] = value
    return MappingProxyType(skeletons), MappingProxyType(min_chars)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_active_pack: ContentPack | None = None


def set_active_pack(pack: ContentPack) -> None:
    """Install the process-wide pack.

    Most engine code receives its pack explicitly. A handful of deep
    validation helpers — the final-payload schema, asset publication, and the
    image renderer — sit several layers below any place a pack could sensibly
    be threaded through, and they only ever need the immutable template
    registry. Those call :func:`active_pack`.

    Entry points (the CLI and the review WSGI app) call this once at startup.
    """
    if not isinstance(pack, ContentPack):
        raise PackError("active pack must be a ContentPack")
    global _active_pack
    _active_pack = pack


def active_pack() -> ContentPack:
    """Return the process-wide pack, or fail loudly if none was installed."""
    if _active_pack is None:
        raise PackError(
            "no active content pack; call set_active_pack() during startup"
        )
    return _active_pack


def load_pack(path: str | Path) -> ContentPack:
    """Load and validate the content pack rooted at ``path``."""
    root = Path(path)
    if not root.is_dir():
        raise PackError(f"content pack directory not found: {root}")

    pack_data = _read_toml(root / "pack.toml", required=True)
    keywords_data = _read_toml(root / "keywords.toml", required=True)
    quality_data = _read_toml(root / "quality.toml", required=True)
    style_data = _read_toml(root / "style.toml", required=True)

    name = _require_text(pack_data, "name", "pack")
    if not _PACK_NAME_PATTERN.fullmatch(name):
        raise PackError(
            "pack.name must be lowercase alphanumeric with dashes, 2-40 chars"
        )

    prompts: dict[str, str] = {}
    prompt_dir = root / "prompts"
    for prompt_name in REQUIRED_PROMPTS + OPTIONAL_PROMPTS:
        prompt_path = prompt_dir / f"{prompt_name}.md"
        if not prompt_path.is_file():
            if prompt_name in REQUIRED_PROMPTS:
                raise PackError(f"pack is missing required prompt: prompts/{prompt_name}.md")
            continue
        if prompt_path.is_symlink():
            raise PackError(f"prompt must not be a symlink: prompts/{prompt_name}.md")
        try:
            text = prompt_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise PackError(f"prompt is unreadable: prompts/{prompt_name}.md") from error
        if not text.strip():
            raise PackError(f"prompt is empty: prompts/{prompt_name}.md")
        prompts[prompt_name] = text

    (
        keyword_groups,
        clickbait_words,
        penalty_per_hit,
        penalty_max,
        credibility,
        cred_prefixes,
        cred_default,
        heat_rules,
        heat_prefixes,
        heat_default,
        weights,
        recency_tiers,
        novelty_dated,
        novelty_undated,
    ) = _read_keywords(keywords_data)

    columns, default_column = _read_columns(pack_data)
    skeletons, min_chars = _read_platforms(pack_data)
    quality = _read_quality(quality_data)

    balance = _require_table(pack_data.get("balance", {}), "pack.balance")

    brief = _require_table(pack_data.get("brief", {}), "pack.brief")

    return ContentPack(
        name=name,
        root=root,
        description=_optional_text(pack_data, "description", "pack"),
        source_credibility=credibility,
        credibility_prefixes=cred_prefixes,
        credibility_default=cred_default,
        heat_rules=heat_rules,
        heat_prefixes=heat_prefixes,
        heat_default=heat_default,
        keyword_groups=keyword_groups,
        clickbait_words=clickbait_words,
        clickbait_penalty_per_hit=penalty_per_hit,
        clickbait_penalty_max=penalty_max,
        score_weights=weights,
        recency_tiers=recency_tiers,
        novelty_base_dated=novelty_dated,
        novelty_base_undated=novelty_undated,
        research_sources=frozenset(
            _require_str_tuple(balance, "research_sources", "pack.balance")
        ),
        practical_sources=frozenset(
            _require_str_tuple(balance, "practical_sources", "pack.balance")
        ),
        practical_prefixes=_require_str_tuple(
            balance, "practical_prefixes", "pack.balance"
        ),
        max_research_per_batch=_require_int(
            balance, "max_research_per_batch", "pack.balance", default=1, minimum=0
        ),
        columns=columns,
        default_column=default_column,
        brief_task=_require_text(brief, "task", "pack.brief"),
        brief_checklist=_require_str_tuple(brief, "checklist", "pack.brief"),
        platform_skeletons=skeletons,
        platform_min_chars=min_chars,
        banned_promises=quality["banned_promises"],
        risky_topics=quality["risky_topics"],
        clickbait_patterns=quality["clickbait_patterns"],
        synthetic_title_patterns=quality["synthetic_title_patterns"],
        title_min_chars=quality["title_min_chars"],
        title_max_chars=quality["title_max_chars"],
        body_min_chars=quality["body_min_chars"],
        max_exclamations=quality["max_exclamations"],
        max_title_question_marks=quality["max_title_question_marks"],
        visual_templates=_read_style(style_data),
        prompts=MappingProxyType(prompts),
    )
