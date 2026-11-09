// Auto-fit text (PLAN.md section 2): the font size shrinks until the text fits its
// box, wrapping at word boundaries; below the minimum size the render fails with the
// scene number instead of overflowing. Lines are measured with
// @remotion/layout-utils and drawn one per line, so the drawing matches the measure.
import {measureText} from '@remotion/layout-utils';
import {FONT, LINE_HEIGHT} from './theme';

export type Fitted = {fontSize: number; lines: string[]; lineHeight: number; tabular?: boolean};

export type FitRequest = {
  text: string;
  width: number;
  height: number;
  maxSize: number;
  minSize: number;
  weight: number;
  sceneId: number;
  label: string; // "headline", "bullet 2", ... (for the error message)
  tabular?: boolean; // equal-width digits, so a count-up never grows wider than its final value
};

const widthOf = (text: string, fontSize: number, fontWeight: number, tabular: boolean) =>
  measureText({
    text,
    fontFamily: FONT,
    fontSize,
    fontWeight,
    validateFontIsLoaded: true,
    ...(tabular ? {fontVariantNumeric: 'tabular-nums'} : {}),
  }).width;

const wrap = (words: string[], size: number, weight: number, width: number, tabular: boolean): string[] | null => {
  const lines: string[] = [];
  let current = '';
  for (const word of words) {
    if (widthOf(word, size, weight, tabular) > width) {
      return null; // one word wider than the box: needs a smaller size
    }
    const candidate = current ? `${current} ${word}` : word;
    if (widthOf(candidate, size, weight, tabular) <= width) {
      current = candidate;
    } else {
      lines.push(current);
      current = word;
    }
  }
  if (current) {
    lines.push(current);
  }
  return lines;
};

export class TextFitError extends Error {}

export const fitText = (r: FitRequest): Fitted => {
  const words = r.text.split(/\s+/).filter(Boolean);
  const maxSize = Math.max(r.maxSize, r.minSize);
  for (let size = maxSize; size >= r.minSize; size -= 2) {
    const lines = wrap(words, size, r.weight, r.width, Boolean(r.tabular));
    if (lines && lines.length * size * LINE_HEIGHT <= r.height) {
      return {fontSize: size, lines, lineHeight: LINE_HEIGHT, tabular: Boolean(r.tabular)};
    }
  }
  throw new TextFitError(
    `Scene ${r.sceneId}: the ${r.label} does not fit its ${r.width}x${r.height} px box even at the ` +
      `minimum font size of ${r.minSize} px. Shorten it and run --from scenes. Text: "${r.text}"`,
  );
};
