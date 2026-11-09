// The three data scenes. Every label and value is the fitted text of the scenes
// JSON; numbers count up from 0 (countup.ts) and end on the value as written.
import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {itemTimings, progressAt} from '../countup';
import type {DataLayout} from '../layout';
import {COLORS} from '../theme';
import type {SceneProps} from '../types';
import {Lines} from './parts';

type Props<T extends DataLayout['type']> = {scene: SceneProps; data: Extract<DataLayout, {type: T}>};

const useAppear = (start: number) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - start, fps, config: {damping: 200}, durationInFrames: 18});
};

const BigNumberCol: React.FC<{col: Extract<DataLayout, {type: 'big_number'}>['cols'][number]; width: number; start: number; frames: number}> = ({
  col,
  width,
  start,
  frames,
}) => {
  const frame = useCurrentFrame();
  const p = useAppear(start);
  const lineW = interpolate(p, [0, 1], [0, Math.min(220, width)]);
  return (
    <div style={{width, opacity: p, transform: `translateY(${(1 - p) * 40}px)`, display: 'flex', flexDirection: 'column', gap: 14}}>
      <Lines f={col.value} color={COLORS.accent} weight={700} align="left" progress={progressAt(frame, {start, frames})} />
      <div style={{height: 6, width: lineW, borderRadius: 3, background: COLORS.panelBorder}} />
      <Lines f={col.label} color={COLORS.sub} weight={500} align="left" />
    </div>
  );
};

export const BigNumberView: React.FC<Props<'big_number'>> = ({scene, data}) => {
  const times = itemTimings(scene.durationInFrames, scene.lineStarts, data.cols.length, 14);
  return (
    <div style={{display: 'flex', gap: data.gap, alignItems: 'flex-start'}}>
      {data.cols.map((c, i) => (
        <BigNumberCol key={i} col={c} width={data.colW} start={times[i].start} frames={times[i].frames} />
      ))}
    </div>
  );
};

const BarRow: React.FC<{data: Extract<DataLayout, {type: 'bar_chart'}>; i: number; start: number; frames: number}> = ({data, i, start, frames}) => {
  const frame = useCurrentFrame();
  const row = data.rows[i];
  const appear = useAppear(start - 6);
  const grow = progressAt(frame, {start, frames});
  const eased = 1 - Math.pow(1 - grow, 3);
  const barW = Math.max(row.scale > 0 ? 4 : 0, Math.round(row.scale * data.barMaxW * eased));
  return (
    <div style={{display: 'flex', alignItems: 'center', height: data.rowH, opacity: appear}}>
      <div style={{width: data.labelW, flex: `0 0 ${data.labelW}px`, display: 'flex', justifyContent: 'flex-end'}}>
        <Lines f={row.label} color={COLORS.sub} weight={500} align="right" />
      </div>
      <div style={{width: 36, flex: '0 0 36px'}} />
      <div
        data-testid="bar"
        style={{width: barW, flex: `0 0 ${barW}px`, height: data.barH, borderRadius: 8, background: COLORS.accent}}
      />
      <div style={{width: 24, flex: '0 0 24px'}} />
      <div style={{width: data.valueW}}>
        <Lines f={row.value} color={COLORS.text} weight={700} align="left" progress={grow} />
      </div>
    </div>
  );
};

export const BarChartView: React.FC<Props<'bar_chart'>> = ({scene, data}) => {
  const times = itemTimings(scene.durationInFrames, scene.lineStarts, data.rows.length, 6);
  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: data.gap}}>
      {data.rows.map((_, i) => (
        <BarRow key={i} data={data} i={i} start={times[i].start} frames={times[i].frames} />
      ))}
    </div>
  );
};

const PriceCard: React.FC<{data: Extract<DataLayout, {type: 'price_cards'}>; i: number; start: number; frames: number}> = ({data, i, start, frames}) => {
  const frame = useCurrentFrame();
  const card = data.cards[i];
  const p = useAppear(start - 8);
  return (
    <div
      style={{
        width: data.cardW,
        height: data.cardH,
        boxSizing: 'border-box',
        padding: 44,
        borderRadius: 28,
        background: COLORS.panel,
        border: `3px solid ${COLORS.panelBorder}`,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        opacity: p,
        transform: `translateY(${(1 - p) * 50}px) scale(${0.94 + 0.06 * p})`,
      }}
    >
      <Lines f={card.label} color={COLORS.sub} weight={600} align="left" />
      <Lines f={card.value} color={COLORS.accent} weight={700} align="left" progress={progressAt(frame, {start, frames})} />
    </div>
  );
};

export const PriceCardsView: React.FC<Props<'price_cards'>> = ({scene, data}) => {
  const times = itemTimings(scene.durationInFrames, scene.lineStarts, data.cards.length, 12);
  return (
    <div style={{display: 'flex', gap: data.gap}}>
      {data.cards.map((_, i) => (
        <PriceCard key={i} data={data} i={i} start={times[i].start} frames={times[i].frames} />
      ))}
    </div>
  );
};

export const DataView: React.FC<{scene: SceneProps; data: DataLayout}> = ({scene, data}) => {
  if (data.type === 'bar_chart') {
    return <BarChartView scene={scene} data={data} />;
  }
  if (data.type === 'price_cards') {
    return <PriceCardsView scene={scene} data={data} />;
  }
  return <BigNumberView scene={scene} data={data} />;
};
