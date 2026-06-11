import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRootCandidates = [
  path.resolve(currentDir, "../../.."),
  path.resolve(currentDir, "../../../.."),
];
const repoRoot =
  repoRootCandidates.find((candidate) =>
    fs.existsSync(path.join(candidate, "docs", "personalized")),
  ) ?? repoRootCandidates[0];
const personalizedRoot = path.join(repoRoot, "docs", "personalized");
const poolsDir = path.join(personalizedRoot, "pools");
const logsDir = path.join(personalizedRoot, "logs");
const l1Dir = path.join(personalizedRoot, "l1");
const l2Dir = path.join(personalizedRoot, "l2");
const legacyReviewsDir = path.join(personalizedRoot, "reviews");
const digestDir = path.join(personalizedRoot, "digest");
const legacyDailyDir = path.join(personalizedRoot, "daily");

type DirectionId =
  | "llm_memory"
  | "dataset_eval"
  | "poi_companion"
  | "acceleration"
  | "neuro_language_memory"
  | "other";

export interface DirectionDefinition {
  id: DirectionId;
  label: string;
  shortLabel: string;
  level: number;
}

interface PoolPaper {
  paper_id: string;
  arxiv_short_id?: string;
  published_date?: string;
  title?: string;
  authors?: string;
  authors_full?: string[];
  paper_url?: string;
  pdf_url?: string;
  code_link?: string | null;
  abstract?: string;
  matched_topics?: string[];
  matched_topic?: string;
}

interface NormalizedL1Paper extends PoolPaper {
  paper_id: string;
  decision: "level2" | "archive_only" | "reject" | string;
  matched_tracks: string[];
  total_score: number | null;
  reason_cn: string | null;
  archive_reason_cn: string | null;
}

interface NormalizedL2Paper {
  paper_id: string;
  title?: string;
  passed_l2: boolean;
  decision: string;
  priority?: string;
  summary_cn: string | null;
  recommended_action_cn: string | null;
  relevance: number | null;
}

interface DigestEntry {
  paper_id: string;
  title?: string;
  summary_cn?: string | null;
  why_relevant_cn?: string | null;
  recommended_action_cn?: string | null;
  reason_cn?: string | null;
  message?: string | null;
}

export interface DashboardPaper {
  paperId: string;
  title: string;
  authors: string[];
  publishedDate: string | null;
  paperUrl: string | null;
  pdfUrl: string | null;
  codeLink: string | null;
  abstract: string | null;
  primaryDirection: DirectionDefinition;
  relatedDirections: DirectionDefinition[];
  trackLabels: string[];
  matchedTopics: string[];
  totalScore: number | null;
  relevance: number | null;
  stageBadge: string;
  statusTone: "accent" | "warning" | "muted" | "danger";
  summary: string | null;
  whyRelevant: string | null;
  recommendedAction: string | null;
  archiveReason: string | null;
  failureMessage: string | null;
}

export interface DashboardGroup {
  direction: DirectionDefinition;
  papers: DashboardPaper[];
}

export interface DashboardColumn {
  id: "digest" | "l2" | "l1" | "archived";
  title: string;
  description: string;
  markdownHtml?: string;
  groups: DashboardGroup[];
}

interface DashboardStats {
  poolCount: number;
  l1Count: number;
  l2Count: number;
  digestMustRead: number;
  digestWatchlist: number;
  archivedCount: number;
  rejectedCount: number;
}

export interface DashboardData {
  availableDates: string[];
  latestDate: string | null;
  selectedDate: string;
  stats: DashboardStats;
  columns: DashboardColumn[];
}

export interface DashboardSummary {
  date: string;
  poolCount: number;
  digestMustRead: number;
  l2Count: number;
  archivedCount: number;
}

const DIRECTIONS: DirectionDefinition[] = [
  {
    id: "llm_memory",
    label: "大模型记忆",
    shortLabel: "记忆",
    level: 5,
  },
  {
    id: "dataset_eval",
    label: "训练/评测数据集",
    shortLabel: "数据与评测",
    level: 4,
  },
  {
    id: "poi_companion",
    label: "POI 与陪伴产品",
    shortLabel: "POI/陪伴",
    level: 3,
  },
  {
    id: "acceleration",
    label: "训练与推理加速",
    shortLabel: "加速",
    level: 2,
  },
  {
    id: "neuro_language_memory",
    label: "神经科学 × 语言与记忆",
    shortLabel: "脑科学交叉",
    level: 1,
  },
  {
    id: "other",
    label: "其他交叉方向",
    shortLabel: "其他",
    level: 0,
  },
];

const directionById = new Map(DIRECTIONS.map((direction) => [direction.id, direction]));

const trackLabelMap = new Map<string, string>([
  ["emotional_dialogue_training_data", "情感/心理对话数据"],
  ["tool_use_and_poi_data", "Tool use / POI 数据"],
  ["sft_rl_and_distillation_data", "SFT / RL / Distillation 数据"],
  ["emotional_and_psychological_eval", "情感与心理评测"],
  ["memory_evaluation_and_reliability", "记忆评测与可靠性"],
  ["multi_agent_memory_frameworks", "多智能体记忆框架"],
  ["long_term_memory", "长期记忆"],
  ["personalized_memory_and_user_state", "个性化记忆/用户状态"],
  ["implicit_memory_and_persona", "隐式记忆/人格一致性"],
  ["neuro_language_memory", "脑科学 × 语言记忆"],
  ["training_acceleration", "训练加速"],
  ["inference_acceleration", "推理加速"],
  ["poi_tool_use_companion", "POI / 陪伴 / Tool use"],
  ["poi_companion", "POI / Companion"],
  ["llm_memory", "大模型记忆"],
  ["dataset_eval", "训练/评测数据集"],
  ["acceleration", "训练与推理加速"],
]);

function readTextIfExists(filePath: string): string | null {
  if (!fs.existsSync(filePath)) return null;
  return fs.readFileSync(filePath, "utf8");
}

function readJsonIfExists<T>(filePath: string): T | null {
  const text = readTextIfExists(filePath);
  if (!text) return null;
  return JSON.parse(text) as T;
}

function listJsonDateFiles(dirPath: string): string[] {
  if (!fs.existsSync(dirPath)) return [];
  return fs
    .readdirSync(dirPath)
    .filter((name) => name.endsWith(".json"))
    .map((name) => name.replace(/\.json$/, ""))
    .sort((left, right) => right.localeCompare(left));
}

function canonicalTrackToken(rawTrack: string): string {
  const normalized = rawTrack.trim().toLowerCase();
  const afterArrow = normalized.includes(">")
    ? normalized.split(">").pop() ?? normalized
    : normalized;
  const compact = afterArrow.trim();
  const parts = compact.split(".").filter(Boolean);

  if (parts.length === 0) return compact;
  if (parts.length === 1) return parts[0];

  return parts[parts.length - 1];
}

function directionFromToken(token: string): DirectionDefinition {
  if (
    [
      "multi_agent_memory_frameworks",
      "long_term_memory",
      "personalized_memory_and_user_state",
      "implicit_memory_and_persona",
      "memory_evaluation_and_reliability",
      "llm_memory",
    ].includes(token)
  ) {
    return directionById.get("llm_memory")!;
  }

  if (
    [
      "emotional_dialogue_training_data",
      "tool_use_and_poi_data",
      "sft_rl_and_distillation_data",
      "emotional_and_psychological_eval",
      "dataset_eval",
    ].includes(token)
  ) {
    return directionById.get("dataset_eval")!;
  }

  if (["poi_tool_use_companion", "poi_companion"].includes(token)) {
    return directionById.get("poi_companion")!;
  }

  if (
    ["training_acceleration", "inference_acceleration", "acceleration"].includes(token)
  ) {
    return directionById.get("acceleration")!;
  }

  if (["neuro_language_memory", "neuro_nlp_memory"].includes(token)) {
    return directionById.get("neuro_language_memory")!;
  }

  if (token.includes("memory") || token.includes("persona")) {
    return directionById.get("llm_memory")!;
  }

  if (token.includes("eval") || token.includes("dataset") || token.includes("dialogue")) {
    return directionById.get("dataset_eval")!;
  }

  if (token.includes("companion") || token.includes("poi")) {
    return directionById.get("poi_companion")!;
  }

  if (token.includes("acceler") || token.includes("cache") || token.includes("parallel")) {
    return directionById.get("acceleration")!;
  }

  if (token.includes("neuro") || token.includes("brain") || token.includes("cognitive")) {
    return directionById.get("neuro_language_memory")!;
  }

  return directionById.get("other")!;
}

function directionsForPaper(
  matchedTracks: string[],
  matchedTopics: string[],
): DirectionDefinition[] {
  const tokens = [
    ...matchedTracks.map(canonicalTrackToken),
    ...matchedTopics.map((topic) => topic.trim().toLowerCase()),
  ];
  const deduped = new Map<DirectionId, DirectionDefinition>();

  for (const token of tokens) {
    let direction = directionFromToken(token);

    if (token === "data_sft_rl_eval") {
      direction = directionById.get("dataset_eval")!;
    } else if (token === "memory_personalization") {
      direction = directionById.get("llm_memory")!;
    } else if (token === "training_inference_acceleration") {
      direction = directionById.get("acceleration")!;
    } else if (token === "neuroscience_language_memory") {
      direction = directionById.get("neuro_language_memory")!;
    } else if (token === "poi_ai_companion") {
      direction = directionById.get("poi_companion")!;
    }

    if (direction.id !== "other") {
      deduped.set(direction.id, direction);
    }
  }

  if (deduped.size === 0) {
    return [directionById.get("other")!];
  }

  return Array.from(deduped.values()).sort((left, right) => right.level - left.level);
}

function formatTrackLabel(rawTrack: string): string {
  const token = canonicalTrackToken(rawTrack);
  return trackLabelMap.get(token) ?? token.replaceAll("_", " ");
}

function normalizePoolPaper(rawPaper: Record<string, unknown>): PoolPaper {
  return {
    paper_id: String(rawPaper.paper_id ?? ""),
    arxiv_short_id: asOptionalString(rawPaper.arxiv_short_id),
    published_date: asOptionalString(rawPaper.published_date),
    title: asOptionalString(rawPaper.title),
    authors: asOptionalString(rawPaper.authors),
    authors_full: Array.isArray(rawPaper.authors_full)
      ? rawPaper.authors_full.map((author) => String(author))
      : undefined,
    paper_url: asOptionalString(rawPaper.paper_url),
    pdf_url: asOptionalString(rawPaper.pdf_url),
    code_link: asOptionalString(rawPaper.code_link),
    abstract: asOptionalString(rawPaper.abstract),
    matched_topics: Array.isArray(rawPaper.matched_topics)
      ? rawPaper.matched_topics.map((topic) => String(topic))
      : undefined,
    matched_topic: asOptionalString(rawPaper.matched_topic),
  };
}

function normalizeL1Paper(rawPaper: Record<string, unknown>): NormalizedL1Paper {
  const paper = isRecord(rawPaper.paper) ? rawPaper.paper : rawPaper;
  const l1 = isRecord(rawPaper.l1) ? rawPaper.l1 : rawPaper;
  const normalizedPaper = normalizePoolPaper(paper);

  return {
    ...normalizedPaper,
    paper_id: normalizedPaper.paper_id,
    decision: String(l1.decision ?? "reject"),
    matched_tracks: Array.isArray(l1.matched_tracks)
      ? l1.matched_tracks.map((track) => String(track))
      : [],
    total_score: asNumber(l1.total_score),
    reason_cn: asOptionalString(l1.reason_cn),
    archive_reason_cn: asOptionalString(l1.archive_reason_cn),
  };
}

function normalizeL2Paper(rawPaper: Record<string, unknown>): NormalizedL2Paper {
  return {
    paper_id: String(rawPaper.paper_id ?? ""),
    title: asOptionalString(rawPaper.title),
    passed_l2: Boolean(rawPaper.passed_l2),
    decision: String(rawPaper.decision ?? "normal"),
    priority: asOptionalString(rawPaper.priority),
    summary_cn: asOptionalString(rawPaper.summary_cn),
    recommended_action_cn: asOptionalString(rawPaper.recommended_action_cn),
    relevance: asNumber(rawPaper.relevance),
  };
}

function asOptionalString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function getPoolDateFile(date: string): string {
  return path.join(poolsDir, `${date}.json`);
}

function getLogFile(date: string, stage: "l1" | "l2" | "digest"): string {
  return path.join(logsDir, date, `${stage}.json`);
}

function getL1File(date: string): string {
  return path.join(l1Dir, `${date}.json`);
}

function getDigestMarkdown(date: string): string | null {
  return (
    readTextIfExists(path.join(digestDir, `${date}.md`)) ??
    readTextIfExists(path.join(legacyDailyDir, `${date}.md`))
  );
}

function getL2FallbackPapers(date: string): NormalizedL2Paper[] {
  for (const dirPath of [path.join(l2Dir, date), path.join(legacyReviewsDir, date)]) {
    if (!fs.existsSync(dirPath)) continue;
    return fs
      .readdirSync(dirPath)
      .filter((name) => name.endsWith(".json"))
      .map((name) => readJsonIfExists<Record<string, unknown>>(path.join(dirPath, name)))
      .filter((paper): paper is Record<string, unknown> => paper !== null)
      .map((paper) => normalizeL2Paper(paper));
  }

  return [];
}

function getDigestFallbackMarkdown(digestJson: Record<string, unknown> | null): string {
  if (!digestJson) return "# Digest\n\nNo digest is available for this pool date yet.";

  const overview = asOptionalString(digestJson.overview_cn) ?? "No overview is available yet.";
  const mustRead = Array.isArray(digestJson.must_read) ? digestJson.must_read.length : 0;
  const watchlist = Array.isArray(digestJson.worth_archiving)
    ? digestJson.worth_archiving.length
    : 0;

  return [
    `# Personalized Research Brief - ${String(digestJson.date ?? "")}`,
    "",
    `- Must read: ${mustRead}`,
    `- Watchlist: ${watchlist}`,
    "",
    "## Overview",
    "",
    overview,
  ].join("\n");
}

function renderMarkdown(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: string[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    blocks.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (listItems.length === 0) return;
    blocks.push(`<ul>${listItems.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ul>`);
    listItems = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    if (trimmed === "---") {
      flushParagraph();
      flushList();
      blocks.push("<hr />");
      continue;
    }

    if (trimmed.startsWith("- ")) {
      flushParagraph();
      listItems.push(trimmed.slice(2));
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      blocks.push(`<h${level}>${inlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }

    paragraph.push(trimmed);
  }

  flushParagraph();
  flushList();

  return blocks.join("");
}

function inlineMarkdown(text: string): string {
  const escaped = text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");

  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
}

function buildPaper(
  paperId: string,
  paperLookup: Map<string, PoolPaper>,
  l1Lookup: Map<string, NormalizedL1Paper>,
  overrides: Partial<DashboardPaper>,
): DashboardPaper | null {
  const poolPaper = paperLookup.get(paperId);
  const l1Paper = l1Lookup.get(paperId);

  if (!poolPaper && !l1Paper) return null;

  const matchedTracks = l1Paper?.matched_tracks ?? [];
  const matchedTopics = [
    ...(poolPaper?.matched_topics ?? []),
    ...(poolPaper?.matched_topic ? [poolPaper.matched_topic] : []),
    ...(l1Paper?.matched_topics ?? []),
    ...(l1Paper?.matched_topic ? [l1Paper.matched_topic] : []),
  ].filter(Boolean) as string[];
  const relatedDirections = directionsForPaper(matchedTracks, matchedTopics);
  const primaryDirection = relatedDirections[0] ?? directionById.get("other")!;
  const authors =
    poolPaper?.authors_full ??
    l1Paper?.authors_full ??
    (poolPaper?.authors ? [poolPaper.authors] : l1Paper?.authors ? [l1Paper.authors] : []);

  return {
    paperId,
    title: overrides.title ?? poolPaper?.title ?? l1Paper?.title ?? paperId,
    authors,
    publishedDate: overrides.publishedDate ?? poolPaper?.published_date ?? l1Paper?.published_date ?? null,
    paperUrl: overrides.paperUrl ?? poolPaper?.paper_url ?? l1Paper?.paper_url ?? null,
    pdfUrl: overrides.pdfUrl ?? poolPaper?.pdf_url ?? l1Paper?.pdf_url ?? null,
    codeLink: overrides.codeLink ?? poolPaper?.code_link ?? l1Paper?.code_link ?? null,
    abstract: overrides.abstract ?? poolPaper?.abstract ?? l1Paper?.abstract ?? null,
    primaryDirection,
    relatedDirections,
    trackLabels: matchedTracks.map(formatTrackLabel),
    matchedTopics: Array.from(new Set(matchedTopics)),
    totalScore: overrides.totalScore ?? l1Paper?.total_score ?? null,
    relevance: overrides.relevance ?? null,
    stageBadge: overrides.stageBadge ?? "",
    statusTone: overrides.statusTone ?? "muted",
    summary: overrides.summary ?? null,
    whyRelevant: overrides.whyRelevant ?? null,
    recommendedAction: overrides.recommendedAction ?? null,
    archiveReason: overrides.archiveReason ?? null,
    failureMessage: overrides.failureMessage ?? null,
  };
}

function groupPapers(papers: DashboardPaper[]): DashboardGroup[] {
  const groups = new Map<DirectionId, DashboardPaper[]>();

  for (const paper of papers) {
    const key = paper.primaryDirection.id;
    const group = groups.get(key) ?? [];
    group.push(paper);
    groups.set(key, group);
  }

  return Array.from(groups.entries())
    .map(([directionId, items]) => ({
      direction: directionById.get(directionId)!,
      papers: items.sort((left, right) => {
        const leftScore = left.relevance ?? left.totalScore ?? -1;
        const rightScore = right.relevance ?? right.totalScore ?? -1;
        return rightScore - leftScore || left.paperId.localeCompare(right.paperId);
      }),
    }))
    .sort((left, right) => right.direction.level - left.direction.level);
}

function normalizeL2Payload(date: string): NormalizedL2Paper[] {
  const logPayload = readJsonIfExists<Record<string, unknown>>(getLogFile(date, "l2"));
  if (logPayload && Array.isArray(logPayload.papers)) {
    return logPayload.papers
      .filter((paper): paper is Record<string, unknown> => isRecord(paper))
      .map((paper) => normalizeL2Paper(paper));
  }

  return getL2FallbackPapers(date);
}

function normalizeL1Payload(date: string): NormalizedL1Paper[] {
  const logPayload = readJsonIfExists<Record<string, unknown>>(getLogFile(date, "l1"));
  const directPayload = readJsonIfExists<Record<string, unknown>>(getL1File(date));
  const source = logPayload ?? directPayload;

  if (!source || !Array.isArray(source.papers)) return [];

  return source.papers
    .filter((paper): paper is Record<string, unknown> => isRecord(paper))
    .map((paper) => normalizeL1Paper(paper));
}

function normalizeDigestEntries(
  rawEntries: unknown,
  kind: "must_read" | "worth_archiving" | "review_failures",
): DigestEntry[] {
  if (!Array.isArray(rawEntries)) return [];
  return rawEntries
    .filter((entry): entry is Record<string, unknown> => isRecord(entry))
    .map((entry) => ({
      paper_id: String(entry.paper_id ?? ""),
      title: asOptionalString(entry.title),
      summary_cn: kind === "must_read" ? asOptionalString(entry.summary_cn) : null,
      why_relevant_cn: kind === "must_read" ? asOptionalString(entry.why_relevant_cn) : null,
      recommended_action_cn:
        kind === "must_read" ? asOptionalString(entry.recommended_action_cn) : null,
      reason_cn: kind === "worth_archiving" ? asOptionalString(entry.reason_cn) : null,
      message: kind === "review_failures" ? asOptionalString(entry.message) : null,
    }));
}

export function getAvailablePoolDates(): string[] {
  return listJsonDateFiles(poolsDir);
}

export function getDashboardSummaries(): DashboardSummary[] {
  return getAvailablePoolDates().map((date) => {
    const data = getDashboardData(date);
    return {
      date,
      poolCount: data.stats.poolCount,
      digestMustRead: data.stats.digestMustRead,
      l2Count: data.stats.l2Count,
      archivedCount: data.stats.archivedCount,
    };
  });
}

export function getDashboardData(requestedDate?: string): DashboardData {
  const availableDates = getAvailablePoolDates();
  if (availableDates.length === 0) {
    throw new Error("No personalized pool snapshots were found in docs/personalized/pools.");
  }

  const latestDate = availableDates[0] ?? null;
  const selectedDate =
    requestedDate && availableDates.includes(requestedDate) ? requestedDate : latestDate!;
  const poolPayload = readJsonIfExists<Record<string, unknown>>(getPoolDateFile(selectedDate));

  if (!poolPayload || !Array.isArray(poolPayload.papers)) {
    throw new Error(`Pool snapshot is missing or invalid for ${selectedDate}.`);
  }

  const poolPapers = poolPayload.papers
    .filter((paper): paper is Record<string, unknown> => isRecord(paper))
    .map((paper) => normalizePoolPaper(paper));
  const paperLookup = new Map(poolPapers.map((paper) => [paper.paper_id, paper]));

  const l1Papers = normalizeL1Payload(selectedDate);
  const l1Lookup = new Map(l1Papers.map((paper) => [paper.paper_id, paper]));

  const l2Papers = normalizeL2Payload(selectedDate);
  const l2Lookup = new Map(l2Papers.map((paper) => [paper.paper_id, paper]));

  const digestPayload = readJsonIfExists<Record<string, unknown>>(getLogFile(selectedDate, "digest"));
  const digestMarkdown = getDigestMarkdown(selectedDate) ?? getDigestFallbackMarkdown(digestPayload);
  const digestHtml = renderMarkdown(digestMarkdown);

  const mustRead = normalizeDigestEntries(digestPayload?.must_read, "must_read");
  const watchlist = normalizeDigestEntries(digestPayload?.worth_archiving, "worth_archiving");
  const reviewFailures = normalizeDigestEntries(
    digestPayload?.review_failures,
    "review_failures",
  );

  const digestIds = new Set(
    [...mustRead, ...watchlist, ...reviewFailures].map((entry) => entry.paper_id),
  );

  const digestPapers = [
    ...mustRead
      .map((entry) =>
        buildPaper(entry.paper_id, paperLookup, l1Lookup, {
          title: entry.title ?? undefined,
          stageBadge: "重点关注",
          statusTone: "accent",
          summary: entry.summary_cn ?? null,
          whyRelevant: entry.why_relevant_cn ?? null,
          recommendedAction: entry.recommended_action_cn ?? null,
        }),
      )
      .filter((paper): paper is DashboardPaper => paper !== null),
    ...watchlist
      .map((entry) =>
        buildPaper(entry.paper_id, paperLookup, l1Lookup, {
          title: entry.title ?? undefined,
          stageBadge: "观察列表",
          statusTone: "warning",
          summary: entry.reason_cn ?? null,
        }),
      )
      .filter((paper): paper is DashboardPaper => paper !== null),
    ...reviewFailures
      .map((entry) =>
        buildPaper(entry.paper_id, paperLookup, l1Lookup, {
          title: entry.title ?? undefined,
          stageBadge: "复审失败",
          statusTone: "danger",
          failureMessage: entry.message ?? null,
        }),
      )
      .filter((paper): paper is DashboardPaper => paper !== null),
  ];

  const archivedIds = new Set<string>();
  const l2ColumnPapers: DashboardPaper[] = [];

  for (const paper of l2Papers) {
    if (digestIds.has(paper.paper_id)) continue;
    if (paper.decision === "archive_only") {
      archivedIds.add(paper.paper_id);
      continue;
    }

    const builtPaper = buildPaper(paper.paper_id, paperLookup, l1Lookup, {
      title: paper.title ?? undefined,
      stageBadge: paper.passed_l2 ? "L2 通过" : "L2 异常",
      statusTone: paper.passed_l2 ? "accent" : "danger",
      summary: paper.summary_cn,
      recommendedAction: paper.recommended_action_cn,
      relevance: paper.relevance,
      failureMessage: paper.passed_l2 ? null : paper.summary_cn,
    });

    if (builtPaper) l2ColumnPapers.push(builtPaper);
  }

  const l1ColumnPapers: DashboardPaper[] = [];
  const archivedPapers: DashboardPaper[] = [];

  for (const paper of l1Papers) {
    if (digestIds.has(paper.paper_id) || l2Lookup.has(paper.paper_id)) {
      if (paper.decision === "archive_only") {
        archivedIds.add(paper.paper_id);
      }
      continue;
    }

    if (paper.decision === "level2") {
      const builtPaper = buildPaper(paper.paper_id, paperLookup, l1Lookup, {
        stageBadge: "L1 通过",
        statusTone: "muted",
        summary: paper.reason_cn,
        totalScore: paper.total_score,
      });
      if (builtPaper) l1ColumnPapers.push(builtPaper);
      continue;
    }

    if (paper.decision === "archive_only") {
      archivedIds.add(paper.paper_id);
    }
  }

  for (const paperId of archivedIds) {
    const l1Paper = l1Lookup.get(paperId);
    const l2Paper = l2Lookup.get(paperId);
    const builtPaper = buildPaper(paperId, paperLookup, l1Lookup, {
      stageBadge: "已归档",
      statusTone: "warning",
      summary: l1Paper?.reason_cn ?? l2Paper?.summary_cn ?? null,
      archiveReason: l1Paper?.archive_reason_cn ?? null,
      relevance: l2Paper?.relevance ?? null,
      recommendedAction: l2Paper?.recommended_action_cn ?? null,
    });
    if (builtPaper) archivedPapers.push(builtPaper);
  }

  const l1Summary = readJsonIfExists<Record<string, unknown>>(getLogFile(selectedDate, "l1"));
  const l2Summary = readJsonIfExists<Record<string, unknown>>(getLogFile(selectedDate, "l2"));
  const digestSummary = readJsonIfExists<Record<string, unknown>>(getLogFile(selectedDate, "digest"));

  const stats: DashboardStats = {
    poolCount: poolPapers.length,
    l1Count:
      asNumber(l1Summary?.summary && isRecord(l1Summary.summary) ? l1Summary.summary.passed_l1 : null) ??
      l1Papers.filter((paper) => paper.decision === "level2").length,
    l2Count:
      asNumber(l2Summary?.summary && isRecord(l2Summary.summary) ? l2Summary.summary.passed_l2 : null) ??
      l2Papers.filter((paper) => paper.passed_l2).length,
    digestMustRead:
      asNumber(
        digestSummary?.summary && isRecord(digestSummary.summary)
          ? digestSummary.summary.must_read
          : null,
      ) ?? mustRead.length,
    digestWatchlist: watchlist.length,
    archivedCount:
      asNumber(l1Summary?.summary && isRecord(l1Summary.summary) ? l1Summary.summary.archived : null) ??
      archivedPapers.length,
    rejectedCount:
      asNumber(l1Summary?.summary && isRecord(l1Summary.summary) ? l1Summary.summary.rejected : null) ??
      l1Papers.filter((paper) => paper.decision === "reject").length,
  };

  const columns: DashboardColumn[] = [
    {
      id: "digest",
      title: "Digest",
      description: "日报摘要与重点关注，渲染自 markdown。",
      markdownHtml: digestHtml,
      groups: groupPapers(digestPapers),
    },
    {
      id: "l2",
      title: "L2",
      description: "全文可行性复审结果，包含通过与复审异常。",
      groups: groupPapers(l2ColumnPapers),
    },
    {
      id: "l1",
      title: "L1",
      description: "通过相关性筛选、但尚未进入 Digest 的候选论文。",
      groups: groupPapers(l1ColumnPapers),
    },
    {
      id: "archived",
      title: "Archived",
      description: "有价值但暂不推进的归档论文。",
      groups: groupPapers(archivedPapers),
    },
  ];

  return {
    availableDates,
    latestDate,
    selectedDate,
    stats,
    columns,
  };
}
