// Count-up and timing rules of the data scenes (big_number, bar_chart, price_cards).
// Plain TypeScript with no imports, so tests/test_render.py can run it in Node.
//
// Rules (STATUS.md "For T5b"):
// - Only a number that is literally in the value string is animated: the first one
//   ("9" in "9 of 12", "3,000" in "$3,000 a month"). The rest of the string never
//   changes.
// - The count-up ends well before the scene's last frame, and from then on the
//   value string is drawn exactly as the scenes JSON writes it.

// A number as written in an article: 1,500 / 8.9 / 122 / 3000.
const NUMBER = /\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?/;

export type NumberToken = {index: number; text: string; value: number; decimals: number; grouped: boolean};

export const firstNumber = (value: string): NumberToken | null => {
  const m = NUMBER.exec(value);
  if (!m) {
    return null;
  }
  const text = m[0];
  const plain = text.replace(/,/g, '');
  const dot = plain.indexOf('.');
  return {index: m.index, text, value: Number(plain), decimals: dot < 0 ? 0 : plain.length - dot - 1, grouped: text.includes(',')};
};

// Numbers that would read wrong while counting: years (2024) and codes with a
// leading zero (007). They are shown as written from the start.
export const countable = (t: NumberToken): boolean => {
  const plain = t.text.replace(/,/g, '');
  if (/^0\d/.test(plain)) {
    return false;
  }
  if (!t.grouped && t.decimals === 0 && /^\d{4}$/.test(plain) && t.value >= 1900 && t.value <= 2099) {
    return false;
  }
  return t.value > 0;
};

const group = (digits: string): string => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');

const format = (n: number, t: NumberToken): string => {
  const fixed = n.toFixed(t.decimals);
  const [int, frac] = fixed.split('.');
  const head = t.grouped ? group(int) : int;
  return frac === undefined ? head : `${head}.${frac}`;
};

const ease = (p: number) => 1 - Math.pow(1 - p, 3);

// The value string at count-up progress p (0..1). At p >= 1 it is the value itself.
export const countUpText = (value: string, p: number): string => {
  const t = firstNumber(value);
  if (p >= 1 || !t || !countable(t)) {
    return value;
  }
  const scale = Math.pow(10, t.decimals);
  // Floor, so the shown number never passes the real one before the end.
  const n = Math.min(t.value, Math.floor(t.value * ease(Math.max(0, p)) * scale) / scale);
  return value.slice(0, t.index) + format(n, t) + value.slice(t.index + t.text.length);
};

// Frames: every data scene uses these, so the tests can check the last frame.
export const COUNT_FRAMES = 36; // 1.2 s at 30 fps
export const HOLD_FRAMES = 15; // the final value stays on screen at least this long

export const holdFrames = (sceneFrames: number): number => Math.min(HOLD_FRAMES, Math.floor(sceneFrames / 3));

export type ItemTiming = {start: number; frames: number};

// When item i of n starts (frames from the scene start) and how long its count-up
// or growth lasts. Items follow the voiceover lines when the counts match; the whole
// animation always ends HOLD_FRAMES before the scene ends.
export const itemTimings = (sceneFrames: number, lineStarts: number[], n: number, stagger: number): ItemTiming[] => {
  // Very short scenes shrink both the count-up and the hold to a third each.
  const frames = Math.max(1, Math.min(COUNT_FRAMES, Math.floor(sceneFrames / 3)));
  const latest = Math.max(0, sceneFrames - holdFrames(sceneFrames) - frames);
  const out: ItemTiming[] = [];
  for (let i = 0; i < n; i++) {
    const wanted = lineStarts.length === n ? Math.max(10, lineStarts[i]) : 14 + i * stagger;
    out.push({start: Math.min(wanted, latest), frames});
  }
  return out;
};

export const progressAt = (frame: number, t: ItemTiming): number =>
  Math.min(1, Math.max(0, (frame - t.start) / t.frames));

// What item i shows at a frame of its scene.
export const valueAtFrame = (value: string, frame: number, t: ItemTiming): string =>
  countUpText(value, progressAt(frame, t));
