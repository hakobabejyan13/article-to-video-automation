// Small drawing pieces shared by every scene view.
import React from 'react';
import {spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {countUpText} from '../countup';
import type {Fitted} from '../fit';

export const useEnter = (delay: number) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = spring({frame: frame - delay, fps, config: {damping: 200}, durationInFrames: 18});
  return {opacity: p, transform: `translateY(${(1 - p) * 30}px)`};
};

export const Enter: React.FC<{delay: number; children: React.ReactNode; style?: React.CSSProperties}> = ({delay, children, style}) => {
  const e = useEnter(delay);
  return <div style={{...style, ...e}}>{children}</div>;
};

// Fitted text, one div per measured line. With `progress` below 1 the first number
// of the text is counted up (countup.ts); at 1 the lines are drawn as fitted.
export const Lines: React.FC<{
  f: Fitted;
  color: string;
  weight: number;
  align: 'center' | 'left' | 'right';
  progress?: number;
}> = ({f, color, weight, align, progress = 1}) => {
  const numberLine = progress < 1 ? f.lines.findIndex((ln) => /\d/.test(ln)) : -1;
  return (
    <div
      style={{
        fontSize: f.fontSize,
        lineHeight: f.lineHeight,
        fontWeight: weight,
        color,
        textAlign: align,
        ...(f.tabular ? {fontVariantNumeric: 'tabular-nums'} : {}),
      }}
    >
      {f.lines.map((line, i) => (
        <div key={i} style={{whiteSpace: 'nowrap'}}>
          {i === numberLine ? countUpText(line, progress) : line}
        </div>
      ))}
    </div>
  );
};
