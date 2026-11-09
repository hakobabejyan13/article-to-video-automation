// Box sizes per visual type, and the fitted text for each box. Generic: the same
// layout is used for every article; the scenes JSON only fills it.
import {fitText, Fitted} from './fit';
import {CONTENT_W} from './theme';
import type {SceneProps, TextItem} from './types';

export type DataKind = 'big_number' | 'bar_chart' | 'price_cards';
export type Kind = 'title' | 'disclosure' | 'outro' | 'bullets' | 'quote' | DataKind;

export const DATA_KINDS: Kind[] = ['big_number', 'bar_chart', 'price_cards'];

// Data scenes: every label and value fitted to its box. Values use equal-width digits
// so a count-up never grows past the box of the final value.
export type DataLayout =
  | {type: 'big_number'; colW: number; gap: number; cols: {label: Fitted; value: Fitted}[]}
  | {
      type: 'bar_chart';
      labelW: number;
      valueW: number;
      barMaxW: number;
      rowH: number;
      barH: number;
      gap: number;
      rows: {label: Fitted; value: Fitted; scale: number}[];
    }
  | {type: 'price_cards'; cardW: number; cardH: number; gap: number; cards: {label: Fitted; value: Fitted}[]};

export type SceneLayout = {
  kind: Kind;
  align: 'center' | 'left';
  headline: Fitted | null;
  quotes: Fitted[];
  subs: Fitted[];
  bullets: Fitted[];
  data: DataLayout | null;
  tag: Fitted | null;
};

// Height available for text between the top margin and the source tag.
const CONTENT_H = 760;
const GAP = 28;
const ICON_H = 120; // icon plus its gap

type Box = {width: number; height: number; maxSize: number; weight: number};

const kindOf = (s: SceneProps): Kind => {
  const t = s.visual.type;
  if (t === 'card') {
    return (s.visual.variant as Kind) ?? 'title';
  }
  if (t === 'bullets' || t === 'quote') {
    return t;
  }
  if (t === 'big_number' || t === 'bar_chart' || t === 'price_cards') {
    return t;
  }
  throw new Error(`Scene ${s.id}: unknown visual type "${t}"`);
};

// Data scenes draw their icon left of the headline, which leaves the height for the data.
export const INLINE_ICON = 92;
export const INLINE_ICON_GAP = 32;
const DATA_SPEC = {
  headline: {width: CONTENT_W - INLINE_ICON - INLINE_ICON_GAP, height: 180, maxSize: 84, weight: 700},
  sub: {width: CONTENT_W, height: 100, maxSize: 46, weight: 400},
  quote: {width: CONTENT_W, height: 200, maxSize: 60, weight: 600},
};

const SPEC: Record<Kind, {headline: Box; sub: Box; quote: Box}> = {
  title: {
    headline: {width: 1500, height: 340, maxSize: 120, weight: 700},
    sub: {width: 1400, height: 170, maxSize: 56, weight: 400},
    quote: {width: 1400, height: 300, maxSize: 72, weight: 600},
  },
  outro: {
    headline: {width: 1500, height: 340, maxSize: 112, weight: 700},
    sub: {width: 1400, height: 170, maxSize: 56, weight: 400},
    quote: {width: 1400, height: 300, maxSize: 72, weight: 600},
  },
  disclosure: {
    headline: {width: 1360, height: 200, maxSize: 88, weight: 700},
    sub: {width: 1360, height: 250, maxSize: 64, weight: 400},
    quote: {width: 1360, height: 250, maxSize: 64, weight: 600},
  },
  bullets: {
    headline: {width: CONTENT_W, height: 200, maxSize: 88, weight: 700},
    sub: {width: CONTENT_W, height: 110, maxSize: 46, weight: 400},
    quote: {width: CONTENT_W, height: 200, maxSize: 60, weight: 600},
  },
  quote: {
    headline: {width: 1500, height: 160, maxSize: 72, weight: 700},
    sub: {width: 1400, height: 120, maxSize: 46, weight: 400},
    quote: {width: 1500, height: 440, maxSize: 84, weight: 600},
  },
  big_number: DATA_SPEC,
  bar_chart: DATA_SPEC,
  price_cards: DATA_SPEC,
};

const BULLET_W = CONTENT_W - 110; // room for the number badge
const TAG: Box = {width: CONTENT_W, height: 80, maxSize: 30, weight: 500};

export const layoutScene = (s: SceneProps, minFontPx: number): SceneLayout => {
  const kind = kindOf(s);
  const spec = SPEC[kind];
  const fit = (t: TextItem | string, box: Box, label: string, minSize = minFontPx) =>
    fitText({text: typeof t === 'string' ? t : t.text, ...box, minSize, sceneId: s.id, label});
  const of = (role: string) => s.onScreen.filter((t) => t.role === role);

  const heads = of('headline');
  // A second headline is drawn as a sub line rather than dropped.
  const headline = heads.length ? fit(heads[0], spec.headline, 'headline') : null;
  const subs = [...heads.slice(1), ...of('sub')].map((t, i) => fit(t, spec.sub, `sub line ${i + 1}`));
  const quotes = of('quote').map((t, i) => fit(t, spec.quote, `quote ${i + 1}`));

  const isData = DATA_KINDS.includes(kind);
  const used =
    (s.visual.icon && !isData ? ICON_H : 0) +
    (headline ? spec.headline.height + GAP : 0) +
    subs.length * (spec.sub.height + GAP) +
    quotes.length * (spec.quote.height + GAP);
  const rest = Math.max(0, CONTENT_H - used);

  const bulletTexts = of('bullet');
  const bulletH = bulletTexts.length ? (rest - GAP * (bulletTexts.length - 1)) / bulletTexts.length : 0;
  const bullets = bulletTexts.map((t, i) =>
    fit(t, {width: BULLET_W, height: Math.min(bulletH, 200), maxSize: 60, weight: 500}, `bullet ${i + 1}`),
  );

  const data = isData ? layoutData(s, kind as DataKind, rest, minFontPx) : null;

  const tag = s.sourceTag ? fit(s.sourceTag, TAG, 'source tag', Math.min(minFontPx, 24)) : null;

  return {
    kind,
    align: kind === 'bullets' || isData ? 'left' : 'center',
    headline,
    quotes,
    subs,
    bullets,
    data,
    tag,
  };
};

const layoutData = (s: SceneProps, kind: DataKind, rest: number, minFontPx: number): DataLayout => {
  const items = s.visual.items ?? [];
  const n = items.length;
  if (n === 0) {
    throw new Error(`Scene ${s.id}: a ${kind} scene has no items`);
  }
  const fit = (text: string, box: Box, label: string, tabular = false) =>
    fitText({text, ...box, minSize: minFontPx, sceneId: s.id, label, tabular});

  if (kind === 'bar_chart') {
    const scale = s.visual.scale ?? [];
    if (scale.length !== n || scale.some((x) => !(x >= 0 && x <= 1))) {
      throw new Error(`Scene ${s.id}: the bar lengths are missing or wrong in the props; run --from render`);
    }
    const gap = 12;
    const labelW = 460;
    const valueW = 320;
    const rowH = Math.min(112, (rest - gap * (n - 1)) / n);
    const barMaxW = CONTENT_W - labelW - 36 - 24 - valueW;
    return {
      type: 'bar_chart',
      labelW,
      valueW,
      barMaxW,
      rowH,
      barH: Math.max(18, Math.min(64, Math.round(rowH * 0.6))),
      gap,
      rows: items.map((it, i) => ({
        label: fit(it.label, {width: labelW, height: rowH, maxSize: 46, weight: 500}, `bar ${i + 1} label`),
        value: fit(it.value, {width: valueW, height: rowH, maxSize: 52, weight: 700}, `bar ${i + 1} value`, true),
        scale: scale[i],
      })),
    };
  }

  if (kind === 'price_cards') {
    const gap = 40;
    const cardW = Math.min(620, Math.floor((CONTENT_W - gap * (n - 1)) / n));
    const cardH = Math.min(420, rest);
    const inner = cardW - 2 * 44;
    const labelH = 120;
    return {
      type: 'price_cards',
      cardW,
      cardH,
      gap,
      cards: items.map((it, i) => ({
        label: fit(it.label, {width: inner, height: labelH, maxSize: 44, weight: 600}, `card ${i + 1} label`),
        value: fit(it.value, {width: inner, height: cardH - 88 - labelH - 24, maxSize: 96, weight: 700}, `card ${i + 1} value`, true),
      })),
    };
  }

  const gap = 72;
  const colW = Math.floor((CONTENT_W - gap * (n - 1)) / n);
  const valueH = Math.min(260, Math.floor(rest * 0.58));
  const labelH = Math.min(160, rest - valueH - 20);
  return {
    type: 'big_number',
    colW,
    gap,
    cols: items.map((it, i) => ({
      value: fit(it.value, {width: colW, height: valueH, maxSize: 200, weight: 700}, `number ${i + 1} value`, true),
      label: fit(it.label, {width: colW, height: labelH, maxSize: 52, weight: 500}, `number ${i + 1} label`),
    })),
  };
};
